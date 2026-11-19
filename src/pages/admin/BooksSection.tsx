// Admin: every account's books, how much of each is translated, and "share" (a copy for other accounts).
import { useMemo, useState } from "react";
import { Share2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { languageLabel } from "@/lib/languages";
import { call, ranges, when, type AdminBook, type AdminUser } from "./shared";

interface Props {
  token: string;
  books: AdminBook[];
  users: AdminUser[];
  /** Account whose books are listed ("" = all) */
  owner: string;
  onOwner: (userId: string) => void;
  onChanged: () => Promise<void> | void;
}

const BooksSection = ({ token, books, users, owner, onOwner, onChanged }: Props) => {
  const [query, setQuery] = useState("");
  const [sharing, setSharing] = useState<AdminBook | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const listed = useMemo(() => {
    const q = query.trim().toLowerCase();
    return books.filter(
      (b) => (!owner || b.user_id === owner) && (!q || `${b.title} ${b.author ?? ""} ${b.email}`.toLowerCase().includes(q)),
    );
  }, [books, owner, query]);
  const totals = useMemo(
    () => ({ pages: listed.reduce((n, b) => n + b.total_pages, 0), translated: listed.reduce((n, b) => n + b.translated.length, 0) }),
    [listed],
  );

  const open = (book: AdminBook) => {
    setChosen(new Set());
    setSharing(book);
  };
  const share = async () => {
    if (!sharing) return;
    setBusy(true);
    try {
      await call(token, "POST", `/books/${sharing.id}/share`, { user_ids: [...chosen] });
      toast.success(`“${sharing.title}” copied to ${chosen.size} ${chosen.size === 1 ? "account" : "accounts"}`);
      setSharing(null);
      await onChanged();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card data-testid="admin-books">
      <CardHeader>
        <CardTitle className="text-lg">Books ({listed.length})</CardTitle>
        <CardDescription>
          {totals.translated} of {totals.pages} pages translated in this list. Sharing gives the other account its own copy with
          the translations made so far, so nothing is translated or paid for twice.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-3">
          <select
            aria-label="Account"
            className="h-10 min-w-56 rounded-md border border-input bg-background px-3 text-sm"
            value={owner}
            onChange={(e) => onOwner(e.target.value)}
          >
            <option value="">All accounts</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.email} ({u.books})
              </option>
            ))}
          </select>
          <Input className="min-w-56 flex-1" placeholder="Search title, author or email" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>

        {listed.length === 0 ? (
          <p className="text-sm text-muted-foreground">No books.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-2 pr-4 font-medium">Title</th>
                  <th className="py-2 pr-4 font-medium">Account</th>
                  <th className="py-2 pr-4 font-medium">Languages</th>
                  <th className="py-2 pr-4 font-medium">Translated</th>
                  <th className="py-2 pr-4 font-medium">Added</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {listed.map((b) => {
                  const done = b.translated.length;
                  const share100 = b.total_pages ? Math.round((done / b.total_pages) * 100) : 0;
                  return (
                    <tr key={b.id} className="border-t align-top" data-testid="admin-book">
                      <td className="max-w-72 py-2 pr-4">
                        <div className="font-medium break-words">{b.title}</div>
                        <div className="text-xs text-muted-foreground">
                          {[b.author, b.source_format, b.status !== "completed" ? b.status : null].filter(Boolean).join(" · ")}
                        </div>
                        {b.error && <div className="text-xs text-destructive break-words">{b.error}</div>}
                      </td>
                      <td className="py-2 pr-4">{b.email}</td>
                      <td className="py-2 pr-4 whitespace-nowrap">
                        {languageLabel(b.original_locale)} → {languageLabel(b.target_locale)}
                      </td>
                      <td className="min-w-48 py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted" aria-hidden>
                            <div className="h-full bg-accent" style={{ width: `${share100}%` }} />
                          </div>
                          <span className="tabular-nums whitespace-nowrap">
                            {done} / {b.total_pages} pages
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground break-words">
                          {done > 0 ? `Pages ${ranges(b.translated)}` : "Nothing yet"}
                          {b.partial_pages > 0 && ` · ${b.partial_pages} unfinished`}
                          {b.last_read_page > 1 && ` · reader is on page ${b.last_read_page}`}
                        </div>
                      </td>
                      <td className="py-2 pr-4 whitespace-nowrap">{when(b.created_at)}</td>
                      <td className="py-2 text-right">
                        <Button variant="outline" size="sm" disabled={b.status !== "completed"} aria-label={`Share ${b.title}`} onClick={() => open(b)}>
                          <Share2 /> Share
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>

      <Dialog open={sharing !== null} onOpenChange={(o) => !o && setSharing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Share “{sharing?.title}”</DialogTitle>
            <DialogDescription>
              From {sharing?.email}. Each chosen account gets its own copy with {sharing?.translated.length ?? 0} of{" "}
              {sharing?.total_pages ?? 0} pages already translated. The copies are independent afterwards.
            </DialogDescription>
          </DialogHeader>
          <ul className="max-h-72 space-y-1 overflow-y-auto">
            {users
              .filter((u) => u.id !== sharing?.user_id)
              .map((u) => (
                <li key={u.id}>
                  <label className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-[hsl(var(--accent))]"
                      checked={chosen.has(u.id)}
                      onChange={() =>
                        setChosen((prev) => {
                          const next = new Set(prev);
                          if (!next.delete(u.id)) next.add(u.id);
                          return next;
                        })
                      }
                    />
                    <span className="flex-1 break-all">{u.email}</span>
                    {books.some((b) => b.user_id === u.id && b.title === sharing?.title) && (
                      <span className="text-xs text-muted-foreground">has a book with this title</span>
                    )}
                  </label>
                </li>
              ))}
          </ul>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setSharing(null)}>
              Cancel
            </Button>
            <Button disabled={busy || chosen.size === 0} onClick={() => void share()}>
              Share with {chosen.size || "…"} {chosen.size === 1 ? "account" : "accounts"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
};

export default BooksSection;
