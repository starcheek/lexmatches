import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { BookOpen, Plus, LogOut, Upload as UploadIcon, Loader2, TrendingDown, Settings, FileText } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";

import { splitPdf, getPdfPageCount, MAX_PAGES } from "@/lib/pdfSplitter";

const uploadSchema = z.object({
  title: z.string().trim().min(1, "Title is required").max(200, "Title must be less than 200 characters"),
  file: z.instanceof(File).refine(
    (file) => file.type === "application/pdf",
    "File must be a PDF"
  ).refine(
    (file) => file.size <= 100 * 1024 * 1024, // 100MB limit for large PDFs
    "File size must be less than 100MB"
  ),
});

const textSchema = z.object({
  title: z.string().trim().min(1, "Title is required").max(200, "Title must be less than 200 characters"),
  text: z.string().trim().min(10, "Text must be at least 10 characters").max(10000, "Text must be less than 10,000 characters"),
});

interface Book {
  id: string;
  title: string;
  original_locale: string;
  target_locale: string;
  status: string;
  total_pages: number;
  created_at: string;
}

const Dashboard = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [books, setBooks] = useState<Book[]>([]);
  const [user, setUser] = useState<any>(null);
  const [textUploadOpen, setTextUploadOpen] = useState(false);
  const [pdfUploadOpen, setPdfUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState({ current: 0, total: 0, status: '' });
  
  // Upload form state - Text
  const [textTitle, setTextTitle] = useState("");
  const [pastedText, setPastedText] = useState("");
  const [textOriginalLocale, setTextOriginalLocale] = useState("french");
  const [textTargetLocale, setTextTargetLocale] = useState("english");
  
  // Upload form state - PDF
  const [pdfTitle, setPdfTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [pdfOriginalLocale, setPdfOriginalLocale] = useState("french");
  const [pdfTargetLocale, setPdfTargetLocale] = useState("english");

  useEffect(() => {
    checkUser();
    
    // Subscribe to realtime updates for books
    const channel = supabase
      .channel('books-changes')
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'books'
        },
        (payload) => {
          console.log('Book change received:', payload);
          fetchBooks();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const checkUser = async () => {
    const { data: { session } } = await supabase.auth.getSession();
    
    if (!session) {
      navigate("/auth");
      return;
    }

    setUser(session.user);
    await fetchBooks();
    setLoading(false);
  };

  const fetchBooks = async () => {
    const { data, error } = await supabase
      .from("books")
      .select("*")
      .order("created_at", { ascending: false });

    if (error) {
      console.error(error);
    } else {
      setBooks(data || []);
    }
  };

  const handleTextUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pastedText || !textTitle || !user) return;

    const validation = textSchema.safeParse({ title: textTitle, text: pastedText });
    if (!validation.success) {
      const errors = validation.error.errors.map(err => err.message).join(", ");
      toast.error(errors);
      return;
    }

    setUploading(true);

    try {
      const { data: book, error: bookError } = await supabase
        .from("books")
        .insert({
          title: textTitle,
          original_locale: textOriginalLocale,
          target_locale: textTargetLocale,
          user_id: user.id,
          status: 'completed',
          total_pages: 1
        })
        .select()
        .single();

      if (bookError) throw bookError;

      const { error: pageError } = await supabase
        .from("pages")
        .insert({
          book_id: book.id,
          page_number: 1,
          original_text: pastedText,
          status: 'pending'
        });

      if (pageError) throw pageError;

      toast.success("Text uploaded successfully!");
      setTextUploadOpen(false);
      setTextTitle("");
      setPastedText("");
      
    } catch (error: any) {
      console.error('Upload error:', error);
      toast.error(error.message || "Failed to upload text");
    } finally {
      setUploading(false);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !pdfTitle || !user) return;

    const validation = uploadSchema.safeParse({ title: pdfTitle, file });
    if (!validation.success) {
      const errors = validation.error.errors.map(err => err.message).join(", ");
      toast.error(errors);
      return;
    }

    setUploading(true);
    setUploadProgress({ current: 0, total: 0, status: 'Analyzing PDF...' });

    try {
      // Split PDF if needed
      const parts = await splitPdf(file);
      const totalParts = parts.length;
      
      if (totalParts > 1) {
        toast.info(`Large PDF detected! Splitting into ${totalParts} parts (${MAX_PAGES} pages each)`, {
          duration: 5000
        });
      }

      setUploadProgress({ current: 0, total: totalParts, status: `Uploading ${totalParts} part(s)...` });

      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const partTitle = totalParts > 1 
          ? `${pdfTitle} [Part ${part.partNumber}]`
          : pdfTitle;
        
        setUploadProgress({ 
          current: i, 
          total: totalParts, 
          status: totalParts > 1 
            ? `Uploading Part ${i + 1} of ${totalParts}...` 
            : 'Uploading...'
        });

        const { data: book, error: bookError } = await supabase
          .from("books")
          .insert({
            title: partTitle,
            original_locale: pdfOriginalLocale,
            target_locale: pdfTargetLocale,
            user_id: user.id,
            status: 'pending'
          })
          .select()
          .single();

        if (bookError) throw bookError;

        const filePath = `${user.id}/${book.id}.pdf`;
        const { error: storageError } = await supabase.storage
          .from('books')
          .upload(filePath, part.blob);

        if (storageError) throw storageError;

        setUploadProgress({ 
          current: i, 
          total: totalParts, 
          status: totalParts > 1 
            ? `Processing Part ${i + 1} of ${totalParts}...` 
            : 'Processing...'
        });

        const { error: functionError } = await supabase.functions.invoke('process-pdf', {
          body: { bookId: book.id }
        });

        if (functionError) throw functionError;
      }

      setUploadProgress({ current: totalParts, total: totalParts, status: 'Complete!' });
      
      if (totalParts > 1) {
        toast.success(`Book split into ${totalParts} parts and uploaded successfully!`);
      } else {
        toast.success("Book uploaded successfully!");
      }
      
      setPdfUploadOpen(false);
      setPdfTitle("");
      setFile(null);
      setUploadProgress({ current: 0, total: 0, status: '' });
      
    } catch (error: any) {
      console.error('Upload error:', error);
      toast.error(error.message || "Failed to upload book");
    } finally {
      setUploading(false);
    }
  };

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    navigate("/");
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center">
          <BookOpen className="h-12 w-12 text-accent mx-auto mb-4 animate-pulse" />
          <p className="text-muted-foreground">Loading your library...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-reading-bg to-background">
      <header className="border-b border-border/50 bg-card/50 backdrop-blur">
        <div className="container mx-auto px-4 py-4 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <BookOpen className="h-8 w-8 text-accent" />
            <h1 className="text-2xl font-serif font-bold text-primary">LexMatches</h1>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground hidden sm:inline">{user?.email}</span>
            <Button variant="ghost" size="sm" onClick={() => navigate("/settings")}>
              <Settings className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Settings</span>
            </Button>
            <Button variant="outline" size="sm" onClick={handleSignOut}>
              <LogOut className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Sign Out</span>
            </Button>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <h2 className="text-3xl font-serif font-bold text-primary mb-2">Your Library</h2>
          <p className="text-muted-foreground">Upload and manage your language learning materials</p>
        </div>




        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Progress Card */}
          <Card 
            className="border-2 border-accent/30 bg-gradient-to-br from-accent/5 to-accent/10 hover:shadow-soft transition-all cursor-pointer group"
            onClick={() => navigate("/progress")}
          >
            <CardContent className="flex flex-col items-center justify-center py-12">
              <div className="h-16 w-16 rounded-full bg-accent/20 flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
                <TrendingDown className="h-8 w-8 text-accent" />
              </div>
              <h3 className="text-lg font-semibold mb-2 text-center">Check Your Progress!</h3>
              <p className="text-sm text-muted-foreground text-center">
                See how your reading independence improves over time
              </p>
            </CardContent>
          </Card>

          {/* Combined Upload Card */}
          <Card className="border-dashed border-2 border-border hover:border-accent transition-colors group overflow-hidden">
            <CardContent className="p-0">
              {/* Top half - Paste Text */}
              <Dialog open={textUploadOpen} onOpenChange={setTextUploadOpen}>
                <DialogTrigger asChild>
                  <div className="flex flex-col items-center justify-center py-8 border-b border-dashed border-border hover:bg-accent/5 transition-colors cursor-pointer">
                    <div className="h-12 w-12 rounded-full bg-accent/10 flex items-center justify-center mb-3 group-hover:bg-accent/20 transition-colors">
                      <FileText className="h-6 w-6 text-accent" />
                    </div>
                    <h3 className="text-base font-semibold mb-1">Paste Text</h3>
                    <p className="text-xs text-muted-foreground text-center px-4">
                      Quick translate from clipboard
                    </p>
                  </div>
                </DialogTrigger>
                <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                  <DialogHeader>
                    <DialogTitle className="font-serif">Paste Text</DialogTitle>
                    <DialogDescription>
                      Paste text directly for translation
                    </DialogDescription>
                  </DialogHeader>

                  <form onSubmit={handleTextUpload} className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="text-title">Title</Label>
                      <Input
                        id="text-title"
                        value={textTitle}
                        onChange={(e) => setTextTitle(e.target.value)}
                        placeholder="Content title"
                        disabled={uploading}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="pasted-text">Text (Max 10,000 characters)</Label>
                      <Textarea
                        id="pasted-text"
                        value={pastedText}
                        onChange={(e) => setPastedText(e.target.value)}
                        placeholder="Paste your text here..."
                        className="min-h-[150px] font-serif"
                        disabled={uploading}
                      />
                      <p className="text-xs text-muted-foreground">
                        {pastedText.length} / 10,000 characters
                      </p>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="text-original">Original Language</Label>
                        <Select value={textOriginalLocale} onValueChange={setTextOriginalLocale} disabled={uploading}>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="english">English</SelectItem>
                            <SelectItem value="french">French</SelectItem>
                            <SelectItem value="spanish">Spanish</SelectItem>
                            <SelectItem value="german">German</SelectItem>
                            <SelectItem value="italian">Italian</SelectItem>
                            <SelectItem value="portuguese">Portuguese</SelectItem>
                            <SelectItem value="russian">Russian</SelectItem>
                            <SelectItem value="japanese">Japanese</SelectItem>
                            <SelectItem value="latvian">Latvian</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="text-target">Target Language</Label>
                        <Select value={textTargetLocale} onValueChange={setTextTargetLocale} disabled={uploading}>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="english">English</SelectItem>
                            <SelectItem value="french">French</SelectItem>
                            <SelectItem value="spanish">Spanish</SelectItem>
                            <SelectItem value="german">German</SelectItem>
                            <SelectItem value="italian">Italian</SelectItem>
                            <SelectItem value="portuguese">Portuguese</SelectItem>
                            <SelectItem value="russian">Russian</SelectItem>
                            <SelectItem value="japanese">Japanese</SelectItem>
                            <SelectItem value="latvian">Latvian</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <Button 
                      type="submit" 
                      className="w-full" 
                      disabled={uploading || !pastedText || !textTitle}
                    >
                      {uploading ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Uploading...
                        </>
                      ) : (
                        <>
                          <FileText className="h-4 w-4 mr-2" />
                          Upload Text
                        </>
                      )}
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>
              
              {/* Bottom half - Upload PDF */}
              <Dialog open={pdfUploadOpen} onOpenChange={setPdfUploadOpen}>
                <DialogTrigger asChild>
                  <div className="flex flex-col items-center justify-center py-8 hover:bg-accent/5 transition-colors cursor-pointer">
                    <div className="h-12 w-12 rounded-full bg-accent/10 flex items-center justify-center mb-3 group-hover:bg-accent/20 transition-colors">
                      <UploadIcon className="h-6 w-6 text-accent" />
                    </div>
                    <h3 className="text-base font-semibold mb-1">Upload PDF</h3>
                    <p className="text-xs text-muted-foreground text-center px-4">
                      Add a document to read
                    </p>
                  </div>
                </DialogTrigger>
                <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                  <DialogHeader>
                    <DialogTitle className="font-serif">Upload PDF</DialogTitle>
                    <DialogDescription>
                      Upload a PDF document for translation
                    </DialogDescription>
                  </DialogHeader>

                  <form onSubmit={handleUpload} className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="pdf-title">Title</Label>
                      <Input
                        id="pdf-title"
                        value={pdfTitle}
                        onChange={(e) => setPdfTitle(e.target.value)}
                        placeholder="Book title"
                        disabled={uploading}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="file">PDF File (Max 150 pages)</Label>
                      <Input
                        id="file"
                        type="file"
                        accept=".pdf"
                        onChange={(e) => setFile(e.target.files?.[0] || null)}
                        disabled={uploading}
                      />
                      <p className="text-xs text-muted-foreground">
                        Large PDFs are automatically split into {MAX_PAGES}-page parts.
                      </p>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="pdf-original">Original Language</Label>
                        <Select value={pdfOriginalLocale} onValueChange={setPdfOriginalLocale} disabled={uploading}>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="english">English</SelectItem>
                            <SelectItem value="french">French</SelectItem>
                            <SelectItem value="spanish">Spanish</SelectItem>
                            <SelectItem value="german">German</SelectItem>
                            <SelectItem value="italian">Italian</SelectItem>
                            <SelectItem value="portuguese">Portuguese</SelectItem>
                            <SelectItem value="russian">Russian</SelectItem>
                            <SelectItem value="japanese">Japanese</SelectItem>
                            <SelectItem value="latvian">Latvian</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="pdf-target">Target Language</Label>
                        <Select value={pdfTargetLocale} onValueChange={setPdfTargetLocale} disabled={uploading}>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="english">English</SelectItem>
                            <SelectItem value="french">French</SelectItem>
                            <SelectItem value="spanish">Spanish</SelectItem>
                            <SelectItem value="german">German</SelectItem>
                            <SelectItem value="italian">Italian</SelectItem>
                            <SelectItem value="portuguese">Portuguese</SelectItem>
                            <SelectItem value="russian">Russian</SelectItem>
                            <SelectItem value="japanese">Japanese</SelectItem>
                            <SelectItem value="latvian">Latvian</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    
                    {/* Upload progress indicator */}
                    {uploading && uploadProgress.total > 0 && (
                      <div className="space-y-2">
                        <div className="flex justify-between text-sm text-muted-foreground">
                          <span>{uploadProgress.status}</span>
                          <span>{uploadProgress.current}/{uploadProgress.total}</span>
                        </div>
                        <Progress 
                          value={(uploadProgress.current / uploadProgress.total) * 100} 
                          className="h-2"
                        />
                      </div>
                    )}
                    
                    <Button 
                      type="submit" 
                      className="w-full" 
                      disabled={uploading || !file || !pdfTitle}
                    >
                      {uploading ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          {uploadProgress.status || 'Uploading...'}
                        </>
                      ) : (
                        <>
                          <UploadIcon className="h-4 w-4 mr-2" />
                          Upload PDF
                        </>
                      )}
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>
            </CardContent>
          </Card>

          {books.map((book) => (
            <Card 
              key={book.id} 
              className="hover:shadow-soft transition-shadow cursor-pointer"
              onClick={() => navigate(`/read/${book.id}`)}
            >
              <CardHeader>
                <CardTitle className="font-serif">{book.title}</CardTitle>
                <CardDescription>
                  {book.original_locale} → {book.target_locale}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-muted-foreground">{book.total_pages} pages</span>
                  <span className={`px-2 py-1 rounded-full text-xs ${
                    book.status === 'completed' ? 'bg-accent/10 text-accent' :
                    book.status === 'processing' ? 'bg-secondary text-secondary-foreground' :
                    book.status === 'failed' ? 'bg-destructive/10 text-destructive' :
                    'bg-muted text-muted-foreground'
                  }`}>
                    {book.status}
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {books.length === 0 && (
          <div className="text-center py-12">
            <UploadIcon className="h-16 w-16 text-muted-foreground mx-auto mb-4 opacity-50" />
            <p className="text-muted-foreground mb-2">No books yet</p>
            <p className="text-sm text-muted-foreground">Upload your first document to get started</p>
          </div>
        )}
      </main>
    </div>
  );
};

export default Dashboard;