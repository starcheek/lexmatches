// Usage analytics (backend/app/routers/analytics.py). One session per tab; events are batched and posted
// every few seconds and when the tab is hidden. Recorded: page views, clicks (which control, where),
// shortcut keys pressed outside form fields, a sampled mouse path, time and scroll depth per page, script
// errors. Never recorded: anything typed into a field, field values, or the text of the book.

import { toast } from "sonner";
import { getToken } from "./api";

// Problems: error = script or resource failure, api_error = failed request, toast_error = an error message
// was shown, rage_click = the same spot clicked 3+ times within a second, slow = a request took over 8 s.
type EventType =
  | "pageview" | "click" | "key" | "mouse" | "leave"
  | "error" | "api_error" | "toast_error" | "rage_click" | "slow";

const SLOW_MS = 8000;

interface TrackEvent {
  t: number;
  type: EventType;
  path: string;
  name?: string;
  data?: Record<string, unknown>;
}

const FLUSH_MS = 5000;
const MOUSE_SAMPLE_MS = 200;
const MAX_QUEUE = 250;

const uuid = () =>
  crypto.randomUUID?.() ??
  "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (+c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))).toString(16),
  );

/** An id kept in web storage; a fresh one per call when storage is blocked. */
const stored = (store: () => Storage, key: string): string => {
  try {
    const existing = store().getItem(key);
    if (existing) return existing;
    const id = uuid();
    store().setItem(key, id);
    return id;
  } catch {
    return uuid();
  }
};

let session = "";
let queue: TrackEvent[] = [];
let metaSent = false;
let path = "";
let pageStart = 0;
let hiddenSince: number | null = null;
let hiddenMs = 0;
let maxScroll = 0;
let mouse: number[][] = [];
let lastMouse = 0;

const push = (type: EventType, name?: string, data?: Record<string, unknown>) => {
  if (!session || queue.length >= MAX_QUEUE) return;
  queue.push({ t: Date.now(), type, path, name, data });
};

const flushMouse = () => {
  if (!mouse.length) return;
  // points: [ms since the page opened, x and y in thousandths of the viewport, scrollY in px]
  push("mouse", undefined, { w: window.innerWidth, h: window.innerHeight, points: mouse });
  mouse = [];
};

const flush = () => {
  flushMouse();
  if (!queue.length) return;
  const events = queue;
  queue = [];
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const meta = metaSent
    ? undefined
    : {
        visitor: stored(() => localStorage, "lexmatches:visitor"),
        language: navigator.language,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        referrer: document.referrer.slice(0, 500) || undefined,
        screen_w: window.screen.width,
        screen_h: window.screen.height,
      };
  metaSent = true;
  // keepalive lets the last batch leave while the tab closes. Analytics must never break the app: errors are dropped.
  fetch("/api/track", { method: "POST", headers, body: JSON.stringify({ session, meta, events }), keepalive: true }).catch(
    () => undefined,
  );
};

const noteScroll = () => {
  const doc = document.documentElement;
  maxScroll = Math.max(maxScroll, Math.min(1, (window.scrollY + window.innerHeight) / Math.max(1, doc.scrollHeight)));
};

const leave = () => {
  if (!path) return;
  const now = Date.now();
  const hidden = hiddenMs + (hiddenSince === null ? 0 : now - hiddenSince);
  push("leave", undefined, {
    seconds: Math.round((now - pageStart) / 100) / 10,
    active_seconds: Math.round((now - pageStart - hidden) / 100) / 10,
    max_scroll: Math.round(maxScroll * 100) / 100,
  });
};

/** Call on every route change. */
export const trackPage = (next: string) => {
  if (!session || next === path) return;
  leave();
  flushMouse(); // the path so far belongs to the page being left
  path = next;
  pageStart = Date.now();
  hiddenMs = 0;
  hiddenSince = document.hidden ? pageStart : null;
  maxScroll = 0;
  push("pageview", undefined, { w: window.innerWidth, h: window.innerHeight });
  requestAnimationFrame(noteScroll);
};

const CONTROL = "button, a, [role='button'], [role='tab'], [role='menuitem'], [role='switch'], input, select, textarea, label, summary, [data-testid], [data-tok]";

/** A stable label for what was clicked, built from the interface only (never from book text or field values). */
const describe = (target: Element): { name?: string; tag: string } => {
  const el = target.closest(CONTROL);
  if (!el) return { tag: target.tagName.toLowerCase() };
  const tag = el.tagName.toLowerCase();
  const testid = el.getAttribute("data-testid");
  const aria = el.getAttribute("aria-label");
  let name: string | undefined;
  if (testid) name = testid;
  else if (el.hasAttribute("data-tok")) name = el.classList.contains("chunk") ? "reader:chunk" : "reader:word";
  else if (aria) name = aria;
  else if (tag === "input" || tag === "select" || tag === "textarea") {
    name = `${tag}${el.getAttribute("type") ? `:${el.getAttribute("type")}` : ""}#${el.id || el.getAttribute("name") || ""}`;
  } else name = (el.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 60) || tag;
  return { name: name.slice(0, 120), tag };
};

/** "/api/books/<uuid>/pages?numbers=1" -> "/api/books/:id/pages": groups the same call across books. */
const foldUrl = (url: string) =>
  url.split("?")[0].replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, ":id").replace(/[0-9a-f]{16,}/gi, ":id");

/** Every /api call: failures and slow answers become events, and the session id travels with the request
 * so the server's own error log (server_errors) can be matched to this session. */
const watchRequests = () => {
  const native = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    if (typeof input !== "string" || !input.startsWith("/api/") || input.startsWith("/api/track")) return native(input, init);
    const what = `${(init?.method ?? "GET").toUpperCase()} ${foldUrl(input)}`;
    const headers = new Headers(init?.headers);
    headers.set("X-Session", session);
    const started = Date.now();
    try {
      const res = await native(input, { ...init, headers });
      const ms = Date.now() - started;
      if (!res.ok) push("api_error", `${res.status} ${what}`, { status: res.status, ms });
      else if (ms > SLOW_MS) push("slow", what, { ms });
      return res;
    } catch (e) {
      push("api_error", `network ${what}`, { message: String(e).slice(0, 200), ms: Date.now() - started, online: navigator.onLine });
      throw e;
    }
  };
};

/** Error messages the app shows (sonner toasts): what the user was actually told went wrong. */
const watchToasts = () => {
  const show = toast.error;
  toast.error = (message, options) => {
    push("toast_error", typeof message === "string" ? message.slice(0, 120) : "(non-text message)");
    return show(message, options);
  };
};

let recentClicks: number[][] = [];
let lastRage = 0;
/** Three or more clicks within a second on the same spot: the user expected something that did not happen. */
const noteRage = (e: MouseEvent, name: string | undefined) => {
  const now = Date.now();
  recentClicks = recentClicks.filter(([t, x, y]) => now - t < 1000 && Math.hypot(x - e.clientX, y - e.clientY) < 40);
  recentClicks.push([now, e.clientX, e.clientY]);
  if (recentClicks.length >= 3 && now - lastRage > 2000) {
    lastRage = now;
    push("rage_click", name, { count: recentClicks.length });
  }
};

const SHORTCUT_KEYS =new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape", " ", "Tab", "Home", "End", "PageUp", "PageDown"]);

export const initTracking = () => {
  if (session || typeof window === "undefined") return;
  session = stored(() => sessionStorage, "lexmatches:session");

  document.addEventListener(
    "click",
    (e) => {
      if (!(e.target instanceof Element)) return;
      const { name, tag } = describe(e.target);
      noteRage(e, name);
      push("click", name, {
        tag,
        x: Math.round((e.clientX / window.innerWidth) * 1000),
        y: Math.round((e.clientY / window.innerHeight) * 1000),
        scroll_y: Math.round(window.scrollY),
        dead: name === undefined || undefined, // a click on something that is not a control
      });
    },
    true,
  );

  document.addEventListener(
    "keydown",
    (e) => {
      const t = e.target;
      // Nothing typed into a field is ever recorded.
      if (t instanceof HTMLElement && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName))) return;
      if (e.repeat || !(SHORTCUT_KEYS.has(e.key) || e.key.length === 1)) return;
      const mods = `${e.ctrlKey ? "Ctrl+" : ""}${e.metaKey ? "Meta+" : ""}${e.altKey ? "Alt+" : ""}`;
      push("key", mods + (e.key === " " ? "Space" : e.key.length === 1 ? e.key.toLowerCase() : e.key));
    },
    true,
  );

  document.addEventListener(
    "mousemove",
    (e) => {
      const now = Date.now();
      if (now - lastMouse < MOUSE_SAMPLE_MS) return;
      lastMouse = now;
      mouse.push([
        now - pageStart,
        Math.round((e.clientX / window.innerWidth) * 1000),
        Math.round((e.clientY / window.innerHeight) * 1000),
        Math.round(window.scrollY),
      ]);
      if (mouse.length >= 300) flushMouse();
    },
    { passive: true },
  );

  window.addEventListener("scroll", noteScroll, { passive: true });
  watchRequests();
  watchToasts();
  window.addEventListener(
    "error",
    (e) => {
      const el = e.target;
      if (el instanceof HTMLElement) {
        // an image, script or stylesheet that failed to load
        const src = (el as HTMLImageElement).src || (el as HTMLLinkElement).href || "";
        if (!src.startsWith("data:")) push("error", `resource ${el.tagName.toLowerCase()}`, { src: foldUrl(src).slice(0, 200) });
      } else if (e instanceof ErrorEvent) {
        push("error", String(e.message).slice(0, 120), {
          source: `${e.filename}:${e.lineno}:${e.colno}`,
          stack: String(e.error?.stack ?? "").slice(0, 1500) || undefined,
        });
      }
    },
    true,
  );
  window.addEventListener("unhandledrejection", (e) =>
    push("error", String(e.reason).slice(0, 120), { stack: String(e.reason?.stack ?? "").slice(0, 1500) || undefined }),
  );

  document.addEventListener("visibilitychange", () => {
    const now = Date.now();
    if (document.hidden) {
      hiddenSince = now;
      flush();
    } else if (hiddenSince !== null) {
      hiddenMs += now - hiddenSince;
      hiddenSince = null;
    }
  });
  window.addEventListener("pagehide", () => {
    leave();
    flush();
  });
  window.setInterval(flush, FLUSH_MS);
};
