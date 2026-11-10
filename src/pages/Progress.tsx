import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowLeft, BookOpen, Loader2, TrendingDown, TrendingUp } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

interface SessionRow {
  book_id: string;
  page_number: number;
  translation_toggle_clicks: number;
}

interface BookStats {
  id: string;
  title: string;
  totalPages: number;
  pagesRead: number;
  totalClicks: number;
  totalWords: number;
  avgClicksPer100Words: number;
  trend: 'up' | 'down' | 'stable';
  points: { page: number; rate: number; clicks: number; words: number; trend: number }[];
}

const countWords = (text: string | null) =>
  text ? (text.trim().match(/[\p{L}\p{N}'’-]+/gu)?.length ?? 0) : 0;

const linearTrend = (points: { page: number; rate: number }[]) => {
  const n = points.length;
  if (n < 2) return { slope: 0, intercept: points[0]?.rate ?? 0 };
  const meanX = points.reduce((s, p) => s + p.page, 0) / n;
  const meanY = points.reduce((s, p) => s + p.rate, 0) / n;
  const denom = points.reduce((s, p) => s + (p.page - meanX) ** 2, 0);
  const slope = denom === 0 ? 0 : points.reduce((s, p) => s + (p.page - meanX) * (p.rate - meanY), 0) / denom;
  return { slope, intercept: meanY - slope * meanX };
};


const Progress = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [books, setBooks] = useState<BookStats[]>([]);
  const [selectedBookId, setSelectedBookId] = useState<string | null>(null);

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) {
      navigate("/auth");
      return;
    }
    await fetchData();
    setLoading(false);
  };

  const fetchData = async () => {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;

    const [{ data: booksData, error: booksError }, { data: sessions, error: sessionsError }] = await Promise.all([
      supabase.from('books').select('id, title, total_pages').eq('user_id', user.id).order('created_at', { ascending: false }),
      supabase
        .from('reading_sessions')
        .select('book_id, page_number, translation_toggle_clicks')
        .eq('user_id', user.id)
        .order('page_number', { ascending: true }),
    ]);

    if (booksError || sessionsError) {
      console.error('Error fetching analytics:', booksError || sessionsError);
      return;
    }

    const rows = (sessions || []) as SessionRow[];
    const bookIds = (booksData || []).map(b => b.id);

    // Word counts per page (used to normalise clicks by page length).
    // Only the pages that actually have a reading session matter, and the API caps
    // each response at 1000 rows — so fetch per book, paginated, for the read pages only.
    const wordsByBookPage = new Map<string, number>();
    const pagesNeeded = new Map<string, Set<number>>();
    rows.forEach(r => {
      if (!pagesNeeded.has(r.book_id)) pagesNeeded.set(r.book_id, new Set());
      pagesNeeded.get(r.book_id)!.add(r.page_number);
    });

    await Promise.all(
      bookIds
        .filter(id => pagesNeeded.has(id))
        .map(async bookId => {
          const pageNumbers = Array.from(pagesNeeded.get(bookId)!);
          for (let i = 0; i < pageNumbers.length; i += 200) {
            const chunk = pageNumbers.slice(i, i + 200);
            const { data: pagesData, error: pagesError } = await supabase
              .from('pages')
              .select('book_id, page_number, original_text')
              .eq('book_id', bookId)
              .in('page_number', chunk);

            if (pagesError) {
              console.error('Error fetching page word counts:', pagesError);
              continue;
            }
            (pagesData || []).forEach(p => {
              wordsByBookPage.set(`${p.book_id}:${p.page_number}`, countWords(p.original_text));
            });
          }
        })
    );

    const stats: BookStats[] = (booksData || []).map(book => {
      const perPage = new Map<number, number>();
      rows
        .filter(r => r.book_id === book.id)
        .forEach(r => {
          perPage.set(r.page_number, (perPage.get(r.page_number) || 0) + (r.translation_toggle_clicks || 0));
        });

      const base = Array.from(perPage.entries())
        .map(([page, clicks]) => {
          const words = wordsByBookPage.get(`${book.id}:${page}`) || 0;
          return {
            page,
            clicks,
            words,
            rate: words > 0 ? Math.round((clicks / words) * 1000) / 10 : 0,
          };
        })
        .filter(p => p.words > 0)
        .sort((a, b) => a.page - b.page);

      const { slope, intercept } = linearTrend(base);
      const points = base.map(p => ({
        ...p,
        trend: Math.max(0, Math.round((slope * p.page + intercept) * 10) / 10),
      }));

      const totalClicks = base.reduce((s, p) => s + p.clicks, 0);
      const totalWords = base.reduce((s, p) => s + p.words, 0);
      const pagesRead = base.length;

      return {
        id: book.id,
        title: book.title,
        totalPages: book.total_pages || 0,
        pagesRead,
        totalClicks,
        totalWords,
        avgClicksPer100Words: totalWords ? Math.round((totalClicks / totalWords) * 1000) / 10 : 0,
        trend: base.length < 3 || Math.abs(slope) < 0.02 ? 'stable' : slope < 0 ? 'down' : 'up',
        points,
      };
    });


    setBooks(stats);
    setSelectedBookId(prev => prev ?? (stats.find(b => b.pagesRead > 0)?.id || stats[0]?.id || null));
  };


  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-accent mx-auto mb-4 animate-spin" />
          <p className="text-muted-foreground">Loading progress data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-reading-bg to-background">
      <header className="border-b border-border/50 bg-card/50 backdrop-blur">
        <div className="container mx-auto px-4 py-4">
          <Button variant="ghost" onClick={() => navigate("/dashboard")}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Library
          </Button>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-4xl font-serif font-bold text-primary mb-2">Your Learning Progress</h1>
          <p className="text-muted-foreground">
            Per-book comprehension metrics — fewer translation toggles per page means you need less help
          </p>
        </div>

        {books.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-muted-foreground mb-2">No books yet</p>
              <p className="text-sm text-muted-foreground">Upload a book to start tracking your progress.</p>
            </CardContent>
          </Card>
        ) : (
          <div className="max-w-3xl mx-auto space-y-3">
            {books.map(book => {
              const isSelected = book.id === selectedBookId;
              return (
                <div key={book.id} className="space-y-4">
                  <button
                    onClick={() => setSelectedBookId(book.id)}
                    className={`w-full text-left rounded-lg border p-4 transition-all ${
                      isSelected
                        ? 'border-accent bg-accent/10 shadow-sm'
                        : 'border-border bg-card/50 hover:bg-accent/5'
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <BookOpen className="h-4 w-4 mt-1 text-muted-foreground flex-shrink-0" />
                      <div className="min-w-0">
                        <p className="font-serif font-semibold text-primary truncate">{book.title}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {book.pagesRead} of {book.totalPages} pages tracked · avg {book.avgClicksPer100Words} clicks / 100 words
                        </p>

                        <div className="flex items-center gap-1 mt-2 text-xs">
                          {book.trend === 'down' ? (
                            <>
                              <TrendingDown className="h-3.5 w-3.5 text-green-500" />
                              <span className="text-green-500">Improving</span>
                            </>
                          ) : book.trend === 'up' ? (
                            <>
                              <TrendingUp className="h-3.5 w-3.5 text-orange-500" />
                              <span className="text-orange-500">Needs work</span>
                            </>
                          ) : (
                            <span className="text-muted-foreground">Stable</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </button>

                  {isSelected && (
                    <div className="space-y-4 transition-all duration-300 ease-out">
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        <Card>
                          <CardHeader>
                            <CardTitle className="text-sm font-medium text-muted-foreground">Clicks / 100 Words</CardTitle>
                          </CardHeader>
                          <CardContent>
                            <div className="text-3xl font-bold text-primary">{book.avgClicksPer100Words}</div>
                            <p className="text-xs text-muted-foreground mt-1">{book.totalWords.toLocaleString()} words tracked</p>
                          </CardContent>
                        </Card>

                        <Card>
                          <CardHeader>
                            <CardTitle className="text-sm font-medium text-muted-foreground">Pages Tracked</CardTitle>
                          </CardHeader>
                          <CardContent>
                            <div className="text-3xl font-bold text-primary">{book.pagesRead}</div>
                            <p className="text-xs text-muted-foreground mt-1">of {book.totalPages} total</p>
                          </CardContent>
                        </Card>
                        <Card>
                          <CardHeader>
                            <CardTitle className="text-sm font-medium text-muted-foreground">Total Toggles</CardTitle>
                          </CardHeader>
                          <CardContent>
                            <div className="text-3xl font-bold text-primary">{book.totalClicks}</div>
                            <p className="text-xs text-muted-foreground mt-1">Across this book</p>
                          </CardContent>
                        </Card>
                      </div>

                      <Card>
                        <CardHeader>
                          <CardTitle className="font-serif">{book.title} — clicks per 100 words</CardTitle>
                          <CardDescription>
                            Each point is one page, normalised by how many words that page has. The dashed line is the
                            trend — a downward slope means your comprehension is improving as you progress.
                          </CardDescription>
                        </CardHeader>
                        <CardContent>
                          {book.points.length > 0 ? (
                            <ResponsiveContainer width="100%" height={400}>
                              <LineChart data={book.points}>
                                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                                <XAxis
                                  dataKey="page"
                                  stroke="hsl(var(--muted-foreground))"
                                  fontSize={12}
                                  label={{ value: 'Page', position: 'insideBottom', offset: -4 }}
                                />
                                <YAxis
                                  stroke="hsl(var(--muted-foreground))"
                                  fontSize={12}
                                  label={{ value: 'Clicks / 100 words', angle: -90, position: 'insideLeft' }}
                                />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--card))',
                                    border: '1px solid hsl(var(--border))',
                                    borderRadius: '8px'
                                  }}
                                  labelStyle={{ color: 'hsl(var(--foreground))' }}
                                  formatter={(value: number, name: string) => [value, name]}
                                />
                                <Line
                                  type="monotone"
                                  dataKey="rate"
                                  stroke="hsl(var(--accent))"
                                  strokeWidth={2}
                                  dot={{ fill: 'hsl(var(--accent))' }}
                                  name="Clicks / 100 words"
                                />

                                <Line
                                  type="linear"
                                  dataKey="trend"
                                  stroke="hsl(var(--primary))"
                                  strokeWidth={2}
                                  strokeDasharray="6 4"
                                  dot={false}
                                  name="Trend"
                                />
                              </LineChart>
                            </ResponsiveContainer>
                          ) : (
                            <div className="text-center py-12">
                              <p className="text-muted-foreground mb-2">No data for this book yet</p>
                              <p className="text-sm text-muted-foreground">
                                Read a few pages and toggle translations to build the trendline.
                              </p>
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
};

export default Progress;
