import { useEffect, useRef } from "react";

// Cloudflare Turnstile (captcha), rendered explicitly. Its script and iframe come from challenges.cloudflare.com
// (allowed in the Content-Security-Policy in deploy/Caddyfile). The server verifies the token on sign-up.
interface TurnstileApi {
  render: (el: HTMLElement, options: Record<string, unknown>) => string;
  remove: (widgetId: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
let loading: Promise<void> | null = null;

const loadScript = () => {
  if (window.turnstile) return Promise.resolve();
  loading ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SRC;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      loading = null;
      reject(new Error("Captcha could not be loaded"));
    };
    document.head.appendChild(s);
  });
  return loading;
};

/** Calls onToken with a fresh token when solved, null when it expires or fails. Remount (key) to reset. */
export const Turnstile = ({ siteKey, onToken }: { siteKey: string; onToken: (token: string | null) => void }) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let widget: string | undefined;
    let cancelled = false;
    loadScript()
      .then(() => {
        if (cancelled || !ref.current || !window.turnstile) return;
        widget = window.turnstile.render(ref.current, {
          sitekey: siteKey,
          callback: (token: string) => onToken(token),
          "expired-callback": () => onToken(null),
          "error-callback": () => onToken(null),
        });
      })
      .catch(() => onToken(null));
    return () => {
      cancelled = true;
      if (widget && window.turnstile) window.turnstile.remove(widget);
    };
  }, [siteKey, onToken]);

  return <div ref={ref} className="flex justify-center" />;
};
