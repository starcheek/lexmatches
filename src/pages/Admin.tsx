// Owner page: test accounts and the sign-up switch. Opened as /admin#<ADMIN_TOKEN>; the token is moved from
// the address bar into sessionStorage (a URL fragment is never sent to the server or to Cloudflare).
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Copy, KeyRound, Loader2, RefreshCw, Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const TOKEN_KEY = "lexmatches:admin";

interface AdminUser {
  id: string;
  email: string;
  created_at: string;
  books: number;
  translated_pages: number;
  sessions: number;
  last_seen: string | null;
  last_ip: string | null;
}

interface Problems {
  days: number;
  groups: { source: "page" | "server"; kind: string; what: string; times: number; sessions: number; users: number; last: string }[];
  server: { ts: string; method: string; path: string; status: number | null; duration_ms: number | null; detail: string | null; traceback: string | null; ip: string | null; email: string | null }[];
  page: { ts: string; type: string; path: string; name: string | null; data: Record<string, unknown> | null; email: string | null }[];
  failed: { ts: string; kind: "book" | "page"; title: string; page_number: number | null; error: string | null; email: string }[];
  dead_clicks: { page: string; tag: string | null; times: number; sessions: number }[];
}

const KIND: Record<string, string> = {
  error: "Script or resource error",
  api_error: "Request failed (seen in browser)",
  toast_error: "Error message shown",
  rage_click: "Rage click",
  slow: "Slow request (over 8 s)",
  server_error: "Server crash",
  rejected: "Request rejected",
  job: "Background job crashed",
};

interface Issued {
  email: string;
  password: string;
}

const readToken = (): string => {
  try {
    const fromHash = decodeURIComponent(window.location.hash.slice(1));
    if (fromHash) {
      sessionStorage.setItem(TOKEN_KEY, fromHash);
      window.history.replaceState(null, "", window.location.pathname);
      return fromHash;
    }
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
};

async function call<T>(token: string, method: string, path: string, body?: unknown): Promise<T> {
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

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never";

const Admin = () => {
  const [token, setToken] = useState(readToken);
  const [draft, setDraft] = useState("");
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [signupOpen, setSignupOpen] = useState<boolean | null>(null);
  const [email, setEmail] = useState("");
  const [issued, setIssued] = useState<Issued | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<Problems | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const s = await call<{ signup_open: boolean }>(token, "GET", "/settings");
      setSignupOpen(s.signup_open);
      setUsers(await call<AdminUser[]>(token, "GET", "/users"));
      setProblems(await call<Problems>(token, "GET", "/problems?days=7"));
      setError(null);
    } catch (e) {
      setUsers(null);
      setError((e as Error).message);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (action: () => Promise<void>) => {
    try {
      await action();
      await load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const create = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      setIssued(await call<Issued>(token, "POST", "/users", { email }));
      setEmail("");
    });
  };

  const copy = (i: Issued) => {
    const auth = `${window.location.origin}/auth`;
    // The first link signs in by itself and opens the sample book (see Auth.tsx).
    const text =
      `LexMatches test account\nOpen directly: ${auth}#login=${encodeURIComponent(i.email)}:${encodeURIComponent(i.password)}\n` +
      `Or sign in at ${auth}\nEmail: ${i.email}\nPassword: ${i.password}`;
    navigator.clipboard.writeText(text).then(
      () => toast.success("Login details copied"),
      () => toast.error("Could not copy; select the text instead"),
    );
  };

  if (!token || (error && !users)) {
    return (
      <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-4 px-4">
        <h1 className="font-serif text-2xl font-bold text-primary">Admin</h1>
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            try {
              sessionStorage.setItem(TOKEN_KEY, draft.trim());
            } catch {
              /* kept in memory only */
            }
            setToken(draft.trim());
          }}
        >
          <Label htmlFor="admin-token">Admin token</Label>
          <Input id="admin-token" type="password" autoComplete="off" value={draft} onChange={(e) => setDraft(e.target.value)} />
          <Button type="submit" disabled={!draft.trim()}>Open</Button>
        </form>
      </main>
    );
  }

  if (!users) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-accent" aria-label="Loading" />
      </div>
    );
  }

  return (
    <main className="container mx-auto max-w-5xl space-y-6 px-4 py-8">
      <div className="flex items-center justify-between">
        <h1 className="font-serif text-3xl font-bold text-primary">Admin</h1>
        <Button variant="ghost" size="sm" onClick={() => void load()}>
          <RefreshCw /> Refresh
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Public sign-up</CardTitle>
          <CardDescription>
            {signupOpen
              ? "Open: anyone who reaches the site can create an account and translate pages on your API key."
              : "Closed: only the accounts you create here can sign in."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            data-testid="signup-switch"
            onClick={() => void run(async () => void (await call(token, "PUT", "/settings", { signup_open: !signupOpen })))}
          >
            {signupOpen ? "Close sign-up" : "Open sign-up"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">New test account</CardTitle>
          <CardDescription>A password is generated and shown once. Send the login details to the tester.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form className="flex flex-wrap items-end gap-3" onSubmit={create}>
            <div className="min-w-64 flex-1 space-y-1">
              <Label htmlFor="new-email">Email</Label>
              <Input id="new-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="tester@example.com" />
            </div>
            <Button type="submit">
              <UserPlus /> Create account
            </Button>
          </form>
          {issued && (
            <div className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/40 p-3 text-sm" data-testid="issued">
              <span>
                <span className="font-medium">{issued.email}</span> · password{" "}
                <code className="rounded bg-background px-1.5 py-0.5" data-testid="issued-password">{issued.password}</code>
              </span>
              <Button variant="outline" size="sm" onClick={() => copy(issued)}>
                <Copy /> Copy login details
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {problems && (
        <Card data-testid="problems">
          <CardHeader>
            <CardTitle className="text-lg">Problems, last {problems.days} days</CardTitle>
            <CardDescription>
              Errors in the browser and on the server, error messages users were shown, rage clicks and slow requests,
              most frequent first.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6 overflow-x-auto text-sm">
            {problems.groups.length === 0 && problems.failed.length === 0 ? (
              <p className="text-muted-foreground">Nothing recorded.</p>
            ) : (
              <table className="w-full text-left">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Kind</th>
                    <th className="py-2 pr-4 font-medium">What</th>
                    <th className="py-2 pr-4 text-right font-medium">Times</th>
                    <th className="py-2 pr-4 text-right font-medium">Sessions</th>
                    <th className="py-2 pr-4 text-right font-medium">Users</th>
                    <th className="py-2 font-medium">Last</th>
                  </tr>
                </thead>
                <tbody>
                  {problems.groups.map((g) => (
                    <tr key={`${g.source}:${g.kind}:${g.what}`} className="border-t align-top">
                      <td className="py-2 pr-4 whitespace-nowrap">{KIND[g.kind] ?? g.kind}</td>
                      <td className="py-2 pr-4 break-all">{g.what}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{g.times}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{g.sessions}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{g.users}</td>
                      <td className="py-2 whitespace-nowrap">{when(g.last)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {problems.failed.length > 0 && (
              <div>
                <h3 className="mb-2 font-medium">Books and pages that failed</h3>
                <ul className="space-y-1">
                  {problems.failed.map((f, i) => (
                    <li key={i} className="border-t pt-1">
                      {when(f.ts)} · {f.email} · {f.title}
                      {f.page_number ? `, page ${f.page_number}` : ""}: <span className="text-destructive">{f.error ?? "no message"}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {problems.server.length > 0 && (
              <details>
                <summary className="cursor-pointer font-medium">Server log, newest {problems.server.length}</summary>
                <ul className="mt-2 space-y-1">
                  {problems.server.map((s, i) => (
                    <li key={i} className="border-t pt-1">
                      {when(s.ts)} · {s.email ?? "signed out"} · {s.ip ?? "–"} ·{" "}
                      <span className="font-medium">{s.status ?? ""} {s.method} {s.path}</span>
                      {s.duration_ms !== null && ` · ${s.duration_ms} ms`}
                      {s.detail && <div className="break-words text-muted-foreground">{s.detail}</div>}
                      {s.traceback && (
                        <details>
                          <summary className="cursor-pointer text-muted-foreground">Traceback</summary>
                          <pre className="overflow-x-auto whitespace-pre-wrap text-xs">{s.traceback}</pre>
                        </details>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            )}

            {problems.page.length > 0 && (
              <details>
                <summary className="cursor-pointer font-medium">Browser log, newest {problems.page.length}</summary>
                <ul className="mt-2 space-y-1">
                  {problems.page.map((p, i) => (
                    <li key={i} className="border-t pt-1">
                      {when(p.ts)} · {p.email ?? "signed out"} · {KIND[p.type] ?? p.type} on {p.path}:{" "}
                      <span className="font-medium break-all">{p.name ?? "–"}</span>
                      {p.data && <div className="break-all text-xs text-muted-foreground">{JSON.stringify(p.data)}</div>}
                    </li>
                  ))}
                </ul>
              </details>
            )}

            {problems.dead_clicks.length > 0 && (
              <details>
                <summary className="cursor-pointer font-medium">Clicks on things that are not controls</summary>
                <ul className="mt-2 space-y-1">
                  {problems.dead_clicks.map((d, i) => (
                    <li key={i} className="border-t pt-1">
                      {d.page} · &lt;{d.tag ?? "?"}&gt; · {d.times} clicks in {d.sessions} sessions
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Accounts ({users.length})</CardTitle>
          <CardDescription>Translated pages are what costs money (about $0.07 each).</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-2 pr-4 font-medium">Email</th>
                <th className="py-2 pr-4 font-medium">Created</th>
                <th className="py-2 pr-4 text-right font-medium">Books</th>
                <th className="py-2 pr-4 text-right font-medium">Translated pages</th>
                <th className="py-2 pr-4 text-right font-medium">Sessions</th>
                <th className="py-2 pr-4 font-medium">Last seen</th>
                <th className="py-2 pr-4 font-medium">Last IP</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t">
                  <td className="py-2 pr-4 font-medium">{u.email}</td>
                  <td className="py-2 pr-4 whitespace-nowrap">{when(u.created_at)}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{u.books}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{u.translated_pages}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{u.sessions}</td>
                  <td className="py-2 pr-4 whitespace-nowrap">{when(u.last_seen)}</td>
                  <td className="py-2 pr-4">{u.last_ip ?? "–"}</td>
                  <td className="py-2 whitespace-nowrap text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`New password for ${u.email}`}
                      title="New password"
                      onClick={() =>
                        void run(async () => {
                          const r = await call<{ password: string }>(token, "POST", `/users/${u.id}/password`, {});
                          setIssued({ email: u.email, password: r.password });
                        })
                      }
                    >
                      <KeyRound />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Delete ${u.email}`}
                      title="Delete account"
                      onClick={() => {
                        if (window.confirm(`Delete ${u.email} with all their books and progress? This cannot be undone.`)) {
                          void run(() => call<void>(token, "DELETE", `/users/${u.id}`));
                        }
                      }}
                    >
                      <Trash2 />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </main>
  );
};

export default Admin;
