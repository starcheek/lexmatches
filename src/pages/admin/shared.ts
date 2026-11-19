// Shared by the sections of the /admin page (pages/Admin.tsx).

export interface AdminUser {
  id: string;
  email: string;
  created_at: string;
  books: number;
  translated_pages: number;
  sessions: number;
  last_seen: string | null;
  last_ip: string | null;
}

export interface AdminBook {
  id: string;
  user_id: string;
  email: string;
  title: string;
  author: string | null;
  original_locale: string;
  target_locale: string;
  status: "pending" | "processing" | "completed" | "failed";
  error: string | null;
  source_format: string | null;
  total_pages: number;
  last_read_page: number;
  created_at: string;
  /** Numbers of the fully translated pages, ascending */
  translated: number[];
  /** Pages with a translation that was started and not finished */
  partial_pages: number;
}

export interface ServerRequest {
  ts: string;
  method: string;
  path: string;
  status: number | null;
  duration_ms: number | null;
  detail: string | null;
  traceback: string | null;
  ip: string | null;
  email: string | null;
}

export async function call<T>(token: string, method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/admin${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    throw new Error(
      res.status === 404 && path === "/settings"
        ? "The admin area is off: set ADMIN_TOKEN on the server."
        : typeof detail === "string"
          ? detail
          : `Request failed (${res.status})`,
    );
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never";

/** [1, 2, 3, 7, 9, 10] -> "1–3, 7, 9–10" */
export function ranges(numbers: number[]): string {
  const out: string[] = [];
  for (let i = 0; i < numbers.length; ) {
    let j = i;
    while (j + 1 < numbers.length && numbers[j + 1] === numbers[j] + 1) j++;
    out.push(i === j ? `${numbers[i]}` : `${numbers[i]}–${numbers[j]}`);
    i = j + 1;
  }
  return out.join(", ");
}
