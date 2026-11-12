// Typed client for the LexMatches API (same-origin /api; nginx or the Vite dev proxy forwards it).

import { queryClient } from "./queryClient";

const TOKEN_KEY = "lexmatches:token";

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export type Status = "pending" | "processing" | "completed" | "failed";

export interface Book {
  id: string;
  title: string;
  original_locale: string;
  target_locale: string;
  source: "pdf" | "text";
  status: Status;
  error: string | null;
  total_pages: number;
  last_read_page: number;
  /** The beginning of the first page (library list only). */
  preview?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WordPair {
  original: string;
  translation: string;
}

export interface TranslatedSentence {
  source: string;
  /** Natural translation of the whole sentence. */
  translation: string;
  /** Paragraph index on the page: sentences with the same value form one paragraph. */
  paragraph: number;
  repaired?: boolean;
}

/**
 * docs/ARCHITECTURE.md "Translation data contract (v2)". Index-aligned arrays, one entry per sentence;
 * null = not translated yet. Legacy v1 (no `version`): lines[i] = pairs of the i-th visual line, no sentences.
 */
export interface TranslationData {
  version?: number;
  lines: (WordPair[] | null)[];
  sentences?: (TranslatedSentence | null)[];
  fullTranslation?: string;
}

export interface PageImage {
  data: string;
  position?: number;
}

export interface Page {
  id: string;
  book_id: string;
  /** Reading-unit index (1-based). Not necessarily the PDF page: see source_page_start. */
  page_number: number;
  /** First/last PDF page this reading unit comes from (newer ingestion); absent = page_number. */
  source_page_start?: number | null;
  source_page_end?: number | null;
  original_text: string;
  blocks: unknown | null;
  translated_data: TranslationData | null;
  images: PageImage[];
  status: Status;
  error: string | null;
  progress: { done: number; total: number };
  created_at: string;
  updated_at: string;
}

export interface SearchResult {
  pageNumber: number;
  snippet: string;
  matchCount: number;
}

export interface Subscription {
  billing_enabled: boolean;
  subscribed: boolean;
  unlimited: boolean;
  freePages: number;
  product_id?: string | null;
  subscription_end?: string | null;
}

export interface ProgressData {
  books: { id: string; title: string; total_pages: number }[];
  sessions: { book_id: string; page_number: number; translation_toggle_clicks: number; words: number }[];
}

export interface TtsClip {
  audio_url: string;
  content_type: string;
  duration: number;
  /** words[i] = [start, end] seconds of the i-th whitespace token of the requested text; null = silent token */
  words: ([number, number] | null)[];
  voice: string;
  provider: string;
  cached: boolean;
}

export interface TtsVoiceStatus {
  language: string;
  provider: string;
  voice: string | null;
  state: "ready" | "loading" | "downloading" | "missing" | "error" | "unavailable";
  progress?: number;
  error?: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const getToken = (): string | null => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
};

const setToken = (token: string | null) => {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
  // Another user may sign in on this browser: never show the previous user's cached data.
  queryClient.clear();
};

export const isLoggedIn = () => Boolean(getToken());

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") message = body.detail;
      else if (Array.isArray(body?.detail)) message = body.detail.map((d: { msg?: string }) => d.msg).join(", ");
    } catch {
      /* non-JSON error */
    }
    if (res.status === 401 && token) setToken(null);
    throw new ApiError(res.status, message || `Request failed (${res.status})`);
  }
  return res;
}

const json = async <T>(path: string, init?: RequestInit): Promise<T> => (await request(path, init)).json();
const send = <T>(method: string, path: string, body?: unknown) =>
  json<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

interface AuthResponse {
  token: string;
  user: User;
}

export const api = {
  // auth
  async signUp(email: string, password: string) {
    const r = await send<AuthResponse>("POST", "/auth/signup", { email, password });
    setToken(r.token);
    return r.user;
  },
  async signIn(email: string, password: string) {
    const r = await send<AuthResponse>("POST", "/auth/login", { email, password });
    setToken(r.token);
    return r.user;
  },
  signOut() {
    setToken(null);
  },
  me: () => json<User>("/auth/me"),

  // books
  listBooks: () => json<Book[]>("/books"),
  getBook: (id: string) => json<Book>(`/books/${id}`),
  /** Any supported file (PDF, EPUB, FB2, DOCX, ODT, RTF, Markdown, HTML, TXT); the server sniffs the format. */
  uploadBook(file: File, title: string, originalLocale: string, targetLocale: string) {
    const form = new FormData();
    form.append("title", title);
    form.append("original_locale", originalLocale);
    form.append("target_locale", targetLocale);
    form.append("file", file, file.name || "book");
    return json<Book>("/books", { method: "POST", body: form });
  },
  createTextBook: (title: string, originalLocale: string, targetLocale: string, text: string) =>
    send<Book>("POST", "/books/text", { title, original_locale: originalLocale, target_locale: targetLocale, text }),
  /** A web page: fetched, cleaned (navigation, ads, comments removed) and split into pages by the server. */
  importUrl: (url: string, title: string, originalLocale: string, targetLocale: string) =>
    send<Book>("POST", "/books/import", { url, title: title || null, original_locale: originalLocale, target_locale: targetLocale }),
  updateBook: (id: string, patch: { last_read_page?: number; title?: string }) => send<Book>("PATCH", `/books/${id}`, patch),
  deleteBook: (id: string) => request(`/books/${id}`, { method: "DELETE" }),
  async getPdfBlob(id: string) {
    return (await request(`/books/${id}/pdf`)).blob();
  },
  getPages(bookId: string, opts: { numbers?: number[]; status?: Status } = {}) {
    const params = new URLSearchParams();
    if (opts.numbers) params.set("numbers", opts.numbers.join(","));
    if (opts.status) params.set("status", opts.status);
    const qs = params.toString();
    return json<Page[]>(`/books/${bookId}/pages${qs ? `?${qs}` : ""}`);
  },
  getStats: (bookId: string) => json<{ translated: number; total: number }>(`/books/${bookId}/stats`),
  resetFailed: (bookId: string) => send<{ reset: number }>("POST", `/books/${bookId}/reset-failed`),
  search: (bookId: string, q: string) => json<SearchResult[]>(`/books/${bookId}/search?q=${encodeURIComponent(q)}`),
  async exportHtml(bookId: string, pageNumbers: number[]) {
    const res = await request(`/books/${bookId}/export`, {
      method: "POST",
      body: JSON.stringify({ pageNumbers, format: "html" }),
    });
    return res.text();
  },

  // pages
  getPage: (id: string) => json<Page>(`/pages/${id}`),
  translatePage: (id: string) =>
    send<{ status: Status; started: boolean; done: number; total: number }>("POST", `/pages/${id}/translate`),

  // reading sessions / progress
  saveReadingSession: (body: { book_id: string; page_number: number; translation_toggle_clicks: number; session_date?: string }) =>
    send<{ ok: boolean }>("POST", "/reading-sessions", body),
  getProgress: () => json<ProgressData>("/progress"),

  // tts (used by src/features/audio): clip metadata + word timings, then the audio itself
  ttsPrepare: (language?: string) => send<TtsVoiceStatus>("POST", "/tts/prepare", { language }),
  ttsClip: (text: string, language?: string, bookId?: string) =>
    send<TtsClip>("POST", "/tts", { text, language, book_id: bookId }),
  async ttsAudio(audioUrl: string) {
    return (await request(audioUrl.replace(/^\/api/, ""))).blob();
  },

  // billing
  getSubscription: () => json<Subscription>("/subscription"),
  createCheckout: () => send<{ url: string }>("POST", "/billing/checkout"),
  customerPortal: () => send<{ url: string }>("POST", "/billing/portal"),
};
