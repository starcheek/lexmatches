import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, isLoggedIn, type User } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ArrowRight, BookOpen, Languages, MousePointerClick, TrendingDown, Upload, Zap } from "lucide-react";
import ReadingView from "@/components/ReadingView";

const Kbd = ({ children }: { children: React.ReactNode }) => (
  <kbd className="rounded border bg-muted px-1 py-0.5 font-mono text-[0.7rem] text-foreground">{children}</kbd>
);

const Index = () => {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);

  // Demo page in the v2 translation format (see docs/ARCHITECTURE.md): the opening of
  // "Le Tour du monde en quatre-vingts jours" (Jules Verne, 1872, public domain).
  const demoLines: [string, string][][] = [
    [["En l'année 1872,", "in the year 1872,"], ["la maison", "the house"], ["portant", "bearing"], ["le numéro 7", "the number 7"],
     ["de Saville-row", "of Saville Row"], ["était habitée", "was lived in"], ["par Phileas Fogg,", "by Phileas Fogg,"],
     ["l'un des membres", "one of the members"], ["les plus singuliers", "the most peculiar"], ["du Reform-Club", "of the Reform Club"],
     ["de Londres.", "of London."]],
    [["On ne savait", "one knew"], ["rien", "nothing"], ["de lui,", "about him,"], ["sinon que", "except that"], ["c'était", "he was"],
     ["un fort galant homme", "a very gallant man"], ["et l'un", "and one"], ["des plus beaux", "of the finest"],
     ["gentlemen", "gentlemen"], ["de la haute société", "of high society"], ["anglaise.", "English."]],
    [["On disait", "people said"], ["qu'il ressemblait", "that he resembled"], ["à Byron,", "Byron,"], ["mais", "but"],
     ["un Byron", "a Byron"], ["à moustaches", "with a moustache"], ["et à favoris,", "and whiskers,"], ["qui aurait vécu", "who might have lived"],
     ["mille ans", "a thousand years"], ["sans vieillir.", "without ageing."]],
  ];
  const demoSentences = [
    "In the year 1872, the house at number 7 Saville Row was lived in by Phileas Fogg, one of the most peculiar members of the Reform Club of London.",
    "Nothing was known of him, except that he was a very gallant man and one of the finest gentlemen of English high society.",
    "People said that he resembled Byron, but a Byron with a moustache and whiskers, who might have lived a thousand years without ageing.",
  ];
  const demoText = demoLines.map((line) => line.map(([o]) => o).join(" ")).join(" ");
  const demoTranslation = {
    version: 2,
    lines: demoLines.map((line) => line.map(([original, translation]) => ({ original, translation }))),
    sentences: demoLines.map((line, i) => ({ source: line.map(([o]) => o).join(" "), translation: demoSentences[i], paragraph: 0 })),
  };

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
          <div className="grid md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            <div className="text-center space-y-3">
              <div className="h-12 w-12 rounded-full bg-accent/10 flex items-center justify-center mx-auto">
                <BookOpen className="h-6 w-6 text-accent" />
              </div>
              <h3 className="text-xl font-serif font-semibold">Upload Documents</h3>
              <p className="text-muted-foreground">
                Import a PDF, EPUB, Word document, text file or web page in any language and we'll extract the text for you
              </p>
            </div>
            <div className="text-center space-y-3">
              <div className="h-12 w-12 rounded-full bg-accent/10 flex items-center justify-center mx-auto">
                <Languages className="h-6 w-6 text-accent" />
              </div>
              <h3 className="text-xl font-serif font-semibold">AI Translation</h3>
              <p className="text-muted-foreground">
                Get accurate word-by-word translations powered by advanced AI
              </p>
            </div>
            <div className="text-center space-y-3">
              <div className="h-12 w-12 rounded-full bg-accent/10 flex items-center justify-center mx-auto">
                <Zap className="h-6 w-6 text-accent" />
              </div>
              <h3 className="text-xl font-serif font-semibold">Interactive Reading</h3>
              <p className="text-muted-foreground">
                Look up single words and phrases, or the whole page, and see how often you needed help
              </p>
            </div>
          </div>
        </section>

        <section id="demo" className="py-16">
          <div className="container mx-auto px-4 text-center mb-8">
            <h3 className="text-3xl font-serif font-bold text-primary mb-3">How it works</h3>
            <p className="mx-auto max-w-2xl text-muted-foreground">
              You read the original. The translation stays hidden until you ask for it, one word at a time, and every lookup is counted.
            </p>
          </div>
          <ol className="mx-4 mb-8 grid gap-4 sm:mx-auto sm:max-w-5xl sm:grid-cols-2 lg:grid-cols-4" data-testid="walkthrough">
            {[
              { icon: <Upload />, title: "Add something to read", text: "Upload a book (PDF, EPUB, DOCX…), paste a text or import a web page in the language you are learning." },
              { icon: <BookOpen />, title: "Read the original", text: "Try to understand each line on your own first. Nothing is translated on screen until you ask." },
              {
                icon: <MousePointerClick />,
                title: "Look up only what you don't know",
                text: (
                  <>
                    Click or tap a word or phrase to see its meaning beneath it. On a keyboard, <Kbd>↑</Kbd> <Kbd>↓</Kbd> move line by line
                    and <Kbd>←</Kbd> or <Kbd>→</Kbd> shows or hides the translation of the whole page.
                  </>
                ),
              },
              { icon: <TrendingDown />, title: "Watch the counter fall", text: "Every lookup is counted per page. Fewer lookups over time means you are understanding more by yourself." },
            ].map((step, i) => (
              <li key={i} className="rounded-xl border bg-card p-5 text-left shadow-sm">
                <div className="mb-3 flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/10 text-accent [&_svg]:h-4 [&_svg]:w-4">{step.icon}</span>
                  <span className="text-sm font-medium text-muted-foreground">Step {i + 1}</span>
                </div>
                <h4 className="mb-1 font-serif text-lg font-semibold">{step.title}</h4>
                <p className="text-sm leading-relaxed text-muted-foreground">{step.text}</p>
              </li>
            ))}
          </ol>
          <p className="mx-4 mb-3 text-center text-sm font-medium text-primary">
            Try it: click a phrase you don't know, or point here and use the arrow keys.
          </p>
          <div className="mx-4 rounded-xl border bg-card py-6 shadow-soft sm:mx-auto sm:max-w-3xl sm:py-8">
            <ReadingView
              pageNumber={1}
              originalText={demoText}
              translationData={demoTranslation}
              onNextPage={() => {}}
              onPrevPage={() => {}}
              totalPages={1}
              bookId="demo"
              originalLocale="french"
              demo
            />
          </div>
          <p className="mx-4 mt-3 text-center text-xs text-muted-foreground">
            Abridged from Jules Verne, <i>Le Tour du monde en quatre-vingts jours</i> (1872), public domain.
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