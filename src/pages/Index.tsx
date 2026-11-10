import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { BookOpen, Languages, Zap, ArrowRight } from "lucide-react";
import ReadingView from "@/components/ReadingView";

const Index = () => {
  const navigate = useNavigate();
  const [user, setUser] = useState<any>(null);

  // Demo content with translations
  const demoText = "Bienvenue à LexMatches. Apprenez les langues en lisant. La traduction apparaît sous chaque mot.";
  const demoTranslation = {
    lines: [
      [
        { original: "Bienvenue", translation: "Welcome" },
        { original: "à", translation: "to" },
        { original: "LexMatches.", translation: "LexMatches." }
      ],
      [
        { original: "Apprenez", translation: "Learn" },
        { original: "les langues", translation: "languages" },
        { original: "en lisant.", translation: "by reading." }
      ],
      [
        { original: "La traduction", translation: "The translation" },
        { original: "apparaît", translation: "appears" },
        { original: "sous", translation: "beneath" },
        { original: "chaque", translation: "each" },
        { original: "mot.", translation: "word." }
      ]
    ],
    fullTranslation: "Welcome to LexMatches. Learn languages by reading. The translation appears beneath each word."
  };

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        setUser(session.user);
      }
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
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
                Import PDFs in any language and we'll extract the text for you
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
                Toggle translations on and off to test your comprehension
              </p>
            </div>
          </div>
        </section>

        <section id="demo" className="py-16">
          <div className="container mx-auto px-4 text-center mb-8">
            <h3 className="text-3xl font-serif font-bold text-primary mb-3">
              See It In Action
            </h3>
            <p className="text-muted-foreground">
              This is how translations appear directly beneath the original text
            </p>
          </div>
          <ReadingView
            pageNumber={1}
            originalText={demoText}
            translationData={demoTranslation}
            onNextPage={() => {}}
            onPrevPage={() => {}}
            totalPages={1}
            bookId="demo"
          />
        </section>
      </main>

      <footer className="border-t border-border/50 py-8 mt-20">
        <div className="container mx-auto px-4 text-center text-muted-foreground text-sm">
          <p>© 2025 LexMatches. Learn languages through reading.</p>
        </div>
      </footer>
    </div>
  );
};

export default Index;