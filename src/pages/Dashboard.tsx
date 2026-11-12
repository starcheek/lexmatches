import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BookOpen, FileText, Link2, Loader2, LogOut, MoreVertical, Settings, Trash2, TrendingDown, Upload as UploadIcon } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { api, isLoggedIn, type Book, type User } from "@/lib/api";
import { LANGUAGES, languageLabel } from "@/lib/languages";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Tip } from "@/components/Tip";
import { cn } from "@/lib/utils";

type AddKind = "file" | "text" | "url";
const MAX_TEXT = 1_000_000; // server limit (app.ingest MAX_TEXT_CHARS)
// The server sniffs the real format from the content; this list only guides the file picker.
const FILE_EXTENSIONS = [".pdf", ".epub", ".fb2", ".docx", ".odt", ".rtf", ".txt", ".md", ".html", ".htm"];
const FILE_FORMATS = "PDF, EPUB, FB2, DOCX, ODT, RTF, TXT, Markdown, HTML";
const EXTENSION = /\.(pdf|epub|fb2|docx|odt|rtf|txt|md|markdown|html?|xhtml)$/i;
const titleSchema = z.string().trim().min(1, "Title is required").max(200, "Title must be less than 200 characters");
const fileSchema = z.object({
  title: titleSchema,
  file: z
    .instanceof(File)
    .refine((f) => !/\.(mobi|azw3?|kfx)$/i.test(f.name), "Kindle files (MOBI, AZW3) are not supported. Convert the book to EPUB first.")
    .refine((f) => f.size <= 100 * 1024 * 1024, "File size must be less than 100 MB"),
});
const textSchema = z.object({
  title: titleSchema,
  text: z.string().trim().min(10, "Text must be at least 10 characters").max(MAX_TEXT, "Text must be less than 1,000,000 characters"),
});
const urlSchema = z.object({
  title: z.string().trim().max(200, "Title must be less than 200 characters"),
  url: z.string().trim().regex(/^https?:\/\/\S+\.\S+/i, "Enter a link that starts with http:// or https://"),
});
const ADD: Record<AddKind, { title: string; description: string; submit: string }> = {
  file: {
    title: "Upload a book",
    description: `${FILE_FORMATS}. Scanned PDFs without a text layer, Kindle files and DRM-protected books are not supported.`,
    submit: "Upload",
  },
  text: { title: "Paste Text", description: "An article, a chapter or a whole book as plain text.", submit: "Add text" },
  url: { title: "Import a web page", description: "We fetch the page and keep the article text; menus, ads and comments are removed.", submit: "Import page" },
};

const STATUS_LABEL: Record<Book["status"], string> = {
  pending: "Queued",
  processing: "Preparing",
  completed: "Ready",
  failed: "Failed",
};

const Dashboard = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [dialog, setDialog] = useState<AddKind | null>(null);
  const [toDelete, setToDelete] = useState<Book | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      navigate("/auth");
      return;
    }
    api.me().then(setUser).catch(() => navigate("/auth"));
  }, [navigate]);

  // Poll while a book is still being split into pages.
  const booksQuery = useQuery({
    queryKey: ["books"],
    queryFn: api.listBooks,
    enabled: isLoggedIn(),
    refetchInterval: (q) => (q.state.data?.some((b) => b.status === "pending" || b.status === "processing") ? 2000 : false),
  });
  const books: Book[] = booksQuery.data ?? [];

  const handleSignOut = () => {
    api.signOut();
    navigate("/");
  };

  const deleteBook = async (book: Book) => {
    try {
      await api.deleteBook(book.id);
      queryClient.setQueryData<Book[]>(["books"], (prev) => prev?.filter((b) => b.id !== book.id));
      try {
        localStorage.removeItem(`lexmatches:bookmark:${book.id}`);
        localStorage.removeItem(`lexmatches:auto-translate:${book.id}`);
      } catch {
        /* ignore */
      }
      toast.success(`Deleted “${book.title}”`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete the book");
    } finally {
      setToDelete(null);
    }
  };

  if (!user || booksQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-center">
          <BookOpen className="mx-auto mb-4 h-10 w-10 animate-pulse text-accent" />
          <p className="text-muted-foreground">Loading your library…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-reading-bg to-background">
      <header className="border-b border-border/50 bg-card/50 backdrop-blur">
        <div className="container mx-auto flex items-center justify-between gap-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <BookOpen className="h-7 w-7 text-accent" />
            <span className="font-serif text-2xl font-bold text-primary">LexMatches</span>
          </div>
          <nav className="flex items-center gap-1 sm:gap-2">
            <span className="mr-2 hidden text-sm text-muted-foreground md:inline">{user.email}</span>
            <Button variant="ghost" size="sm" onClick={() => navigate("/progress")} aria-label="Progress">
              <TrendingDown /> <span className="hidden sm:inline">Progress</span>
            </Button>
            <Button variant="ghost" size="sm" onClick={() => navigate("/settings")} aria-label="Settings">
              <Settings /> <span className="hidden sm:inline">Settings</span>
            </Button>
            <Tip label="Sign out">
              <Button variant="ghost" size="icon" onClick={handleSignOut} aria-label="Sign out">
                <LogOut />
              </Button>
            </Tip>
          </nav>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        <h1 className="mb-6 font-serif text-3xl font-bold text-primary">Your Library</h1>

        {books.length === 0 && (
          <div className="mb-6 rounded-lg border border-dashed bg-card/60 p-6 text-center">
            <p className="font-medium">No books yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Upload a book ({FILE_FORMATS}), paste a text or import a web page in the language you are learning. You read the original; translations are there when you need them.
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div className="grid grid-cols-3 gap-2 rounded-lg border-2 border-dashed border-border p-3 sm:grid-cols-1">
            <AddButton icon={<UploadIcon />} title="Upload a book" subtitle="PDF, EPUB, DOCX, FB2, TXT…" onClick={() => setDialog("file")} />
            <AddButton icon={<FileText />} title="Paste Text" subtitle="An article or chapter" onClick={() => setDialog("text")} />
            <AddButton icon={<Link2 />} title="Web page" subtitle="Import from a link" onClick={() => setDialog("url")} />
          </div>

          {books.map((book) => (
            <BookCard key={book.id} book={book} onOpen={() => navigate(`/read/${book.id}`)} onDelete={() => setToDelete(book)} />
          ))}
        </div>
      </main>

      <AddBookDialog
        kind={dialog}
        onClose={() => setDialog(null)}
        onCreated={async (book) => {
          await queryClient.invalidateQueries({ queryKey: ["books"] });
          setDialog(null);
          if (book.status === "completed") navigate(`/read/${book.id}`);
          else toast.success("Book uploaded. Preparing the pages…");
        }}
      />

      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{toDelete?.title}”?</AlertDialogTitle>
            <AlertDialogDescription>
              The book, its translations, saved audio and reading statistics are removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => toDelete && void deleteBook(toDelete)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

function AddButton({ icon, title, subtitle, onClick }: { icon: React.ReactNode; title: string; subtitle: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col items-center justify-center gap-1 rounded-md p-2 text-center sm:p-3 transition-colors hover:bg-accent/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:h-5 [&_svg]:w-5"
    >
      <span className="mb-1 flex h-10 w-10 items-center justify-center rounded-full bg-accent/10 text-accent">{icon}</span>
      <span className="font-semibold">{title}</span>
      <span className="text-xs text-muted-foreground">{subtitle}</span>
    </button>
  );
}

function BookCard({ book, onOpen, onDelete }: { book: Book; onOpen: () => void; onDelete: () => void }) {
  const busy = book.status === "pending" || book.status === "processing";
  const failed = book.status === "failed";
  return (
    <div
      className="group relative flex flex-col rounded-lg border bg-card p-5 shadow-sm transition-shadow hover:shadow-soft"
      data-testid="book-card"
      data-status={book.status}
    >
      <button
        type="button"
        onClick={onOpen}
        className="text-left after:absolute after:inset-0 after:rounded-lg focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring"
      >
        <h2 className="pr-8 font-serif text-xl font-semibold leading-snug text-card-foreground">{book.title}</h2>
      </button>
      <p className="mt-1 text-sm text-muted-foreground">
        {languageLabel(book.original_locale)} → {languageLabel(book.target_locale)}
      </p>
      {failed && book.error && (
        <p className="mt-3 flex items-start gap-1.5 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {book.error}
        </p>
      )}
      <div className="mt-auto flex items-center justify-between pt-5 text-sm">
        <span className="text-muted-foreground">
          {book.total_pages > 0
            ? `${book.total_pages} page${book.total_pages === 1 ? "" : "s"}${book.last_read_page > 1 ? ` · at page ${book.last_read_page}` : ""}`
            : busy
              ? "Extracting pages…"
              : ""}
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs",
            book.status === "completed" && "bg-accent/10 text-accent",
            busy && "bg-secondary text-secondary-foreground",
            failed && "bg-destructive/10 text-destructive",
          )}
        >
          {busy && <Loader2 className="h-3 w-3 animate-spin" />}
          {STATUS_LABEL[book.status]}
        </span>
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-2 top-2 z-10 h-8 w-8 text-muted-foreground"
            aria-label={`Actions for ${book.title}`}
          >
            <MoreVertical />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}>
            <Trash2 /> Delete book
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function LanguagePicker({ id, label, value, onChange, disabled }: { id: string; label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {LANGUAGES.map((l) => (
            <SelectItem key={l.value} value={l.value}>
              {l.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function AddBookDialog({ kind, onClose, onCreated }: { kind: AddKind | null; onClose: () => void; onCreated: (b: Book) => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [from, setFrom] = useState("french");
  const [to, setTo] = useState("english");
  const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState<AddKind>("file"); // keeps the content while the dialog closes

  useEffect(() => {
    if (kind === null) {
      setTitle("");
      setText("");
      setUrl("");
      setFile(null);
    } else setShown(kind);
  }, [kind]);
  const k = kind ?? shown;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const check =
      k === "file" ? fileSchema.safeParse({ title, file }) : k === "text" ? textSchema.safeParse({ title, text }) : urlSchema.safeParse({ title, url });
    if (!check.success) return void toast.error(check.error.errors.map((x) => x.message).join(", "));
    setBusy(true);
    try {
      const book =
        k === "file"
          ? await api.uploadBook(file!, title.trim(), from, to)
          : k === "text"
            ? await api.createTextBook(title.trim(), from, to, text)
            : await api.importUrl(url.trim(), title.trim(), from, to);
      await onCreated(book);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };
  const incomplete = k === "file" ? !file || !title.trim() : k === "text" ? !text.trim() || !title.trim() : !url.trim();

  return (
    <Dialog open={kind !== null} onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-serif">{ADD[k].title}</DialogTitle>
          <DialogDescription>{ADD[k].description}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          {k === "file" && (
            <div className="space-y-2">
              <Label htmlFor="file">File (max 100 MB)</Label>
              <Input
                id="file"
                type="file"
                accept={FILE_EXTENSIONS.join(",")}
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  setFile(f);
                  if (f && !title) setTitle(f.name.replace(EXTENSION, ""));
                }}
                disabled={busy}
              />
            </div>
          )}
          {k === "url" && (
            <div className="space-y-2">
              <Label htmlFor="page-url">Link</Label>
              <Input id="page-url" type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" disabled={busy} />
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor={`${k}-title`}>{k === "url" ? "Title (optional: the page's own title is used)" : "Title"}</Label>
            <Input
              id={`${k}-title`}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={k === "file" ? "Book title" : k === "text" ? "e.g. Le Petit Prince, chapter 1" : ""}
              disabled={busy}
            />
          </div>
          {k === "text" && (
            <div className="space-y-2">
              <Label htmlFor="pasted-text">Text</Label>
              <Textarea
                id="pasted-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Paste your text here…"
                className="min-h-[180px] font-serif text-base"
                disabled={busy}
              />
              <p className={cn("text-xs", text.length > MAX_TEXT ? "text-destructive" : "text-muted-foreground")}>
                {text.length.toLocaleString()} characters{text.length > MAX_TEXT ? " (max 1,000,000)" : ""}
              </p>
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            <LanguagePicker id="lang-from" label="Language of the text" value={from} onChange={setFrom} disabled={busy} />
            <LanguagePicker id="lang-to" label="Translate into" value={to} onChange={setTo} disabled={busy} />
          </div>
          <Button type="submit" className="w-full" disabled={busy || incomplete}>
            {busy ? <Loader2 className="animate-spin" /> : k === "file" ? <UploadIcon /> : k === "text" ? <FileText /> : <Link2 />}
            {busy ? "Working…" : ADD[k].submit}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default Dashboard;
