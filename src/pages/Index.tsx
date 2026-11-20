import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, isLoggedIn, type User } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ArrowRight, BookOpen, MousePointerClick, TrendingDown, Upload } from "lucide-react";
import ReadingView from "@/components/ReadingView";
import { DEMO_SAMPLES } from "@/lib/demoSamples";
import { cn } from "@/lib/utils";

const Kbd = ({ children }: { children: React.ReactNode }) => (
  <kbd className="rounded border bg-muted px-1 py-0.5 font-mono text-[0.7rem] text-foreground">{children}</kbd>
);

const Index = () => {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);

  // The same demo page in several language pairs (lib/demoSamples.ts)
  const [sampleId, setSampleId] = useState(DEMO_SAMPLES[0].id);
  const sample = DEMO_SAMPLES.find((s) => s.id === sampleId) ?? DEMO_SAMPLES[0];

  useEffect(() => {
    if (!isLoggedIn()) return;
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  const handleGetStarted = () => {
    if (user) {
      navigate("/dashboard");
    } else {
      navigate("/auth");
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-reading-bg to-background">
      <header className="border-b border-border/50 bg-card/50 backdrop-blur">
        <div className="container mx-auto px-4 py-4 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <BookOpen className="h-8 w-8 text-accent" />
            <h1 className="text-2xl font-serif font-bold text-primary">LexMatches</h1>
          </div>
          <Button onClick={handleGetStarted} variant="outline">
            {user ? "Dashboard" : "Sign In"}
          </Button>
        </div>
      </header>

      <main>
        <section className="container mx-auto px-4 py-20 text-center">
          <div className="max-w-3xl mx-auto space-y-8">
            <h2 className="text-5xl md:text-6xl font-serif font-bold text-primary leading-tight">
              Learn Languages
              <br />
              <span className="text-accent">Through Reading</span>
            </h2>
            <p className="text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
              Transform any foreign language document into an interactive learning experience
              with word-by-word translations that appear directly beneath the original text.
            </p>
            <div className="flex gap-4 justify-center">
              <Button size="lg" onClick={handleGetStarted} className="group">
                Get Started
                <ArrowRight className="ml-2 h-4 w-4 group-hover:translate-x-1 transition-transform" />
              </Button>
              <Button size="lg" variant="outline" onClick={() => {
                document.getElementById('demo')?.scrollIntoView({ behavior: 'smooth' });
              }}>
                See Demo
              </Button>
            </div>
          </div>
        </section>

        <section className="container mx-auto px-4 py-16">
          <h3 className="mb-10 text-center text-3xl font-serif font-bold text-primary">How it works</h3>
          <ol className="mx-auto grid max-w-5xl gap-8 sm:grid-cols-2 lg:grid-cols-4" data-testid="walkthrough">
            {[
              { icon: <Upload />, title: "Add a text", text: "Upload a PDF, EPUB or Word file, paste text or import a web page." },
              { icon: <BookOpen />, title: "Read the original", text: "Nothing is translated until you ask." },
              { icon: <MousePointerClick />, title: "Look up what you don't know", text: "Tap a word or phrase to see its AI translation beneath it." },
              { icon: <TrendingDown />, title: "Need less help", text: "Lookups are counted per page. Watch the number fall." },
            ].map((step) => (
              <li key={step.title} className="space-y-3 text-center">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-accent/10 text-accent [&_svg]:h-6 [&_svg]:w-6">
                  {step.icon}
                </div>
                <h4 className="text-xl font-serif font-semibold">{step.title}</h4>
                <p className="text-muted-foreground">{step.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="demo" className="py-16">
          <p className="mx-4 mb-3 text-center text-sm font-medium text-primary">
            Try it: pick a language and tap a phrase. <Kbd>↑</Kbd> <Kbd>↓</Kbd> move by line, <Kbd>←</Kbd> <Kbd>→</Kbd> toggle the whole page.
          </p>
          <div className="mx-4 mb-4 grid grid-cols-2 gap-2 sm:mx-auto sm:max-w-3xl sm:grid-cols-4" role="group" aria-label="Demo language pair" data-testid="demo-pairs">
            {DEMO_SAMPLES.map((s) => (
              <button
                key={s.id}
                type="button"
                aria-pressed={s.id === sample.id}
                onClick={() => setSampleId(s.id)}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                  s.id === sample.id
                    ? "border-accent bg-accent/10 font-medium text-accent"
                    : "bg-card text-muted-foreground hover:border-accent/50 hover:text-foreground",
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
          <div className="mx-4 rounded-xl border bg-card py-6 shadow-soft sm:mx-auto sm:max-w-3xl sm:py-8">
            <ReadingView
              key={sample.id}
              pageNumber={1}
              originalText={sample.text}
              translationData={sample.translation}
              onNextPage={() => {}}
              onPrevPage={() => {}}
              totalPages={1}
              bookId="demo"
              originalLocale={sample.locale}
              demo
            />
          </div>
          <p className="mx-4 mt-3 text-center text-xs text-muted-foreground">
            {sample.locale === "french" ? "Abridged from" : "Abridged and translated from"} Jules Verne,{" "}
            <i>Le Tour du monde en quatre-vingts jours</i> (1872), public domain.
          </p>
        </section>
      </main>

      <footer className="border-t border-border/50 py-8 mt-20">
        <div className="container mx-auto px-4 text-center text-muted-foreground text-sm">
          <p>© 2026 LexMatches. Learn languages through reading.</p>
        </div>
      </footer>
    </div>
  );
};

export default Index;