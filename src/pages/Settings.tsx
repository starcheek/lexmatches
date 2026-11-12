import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTheme } from "next-themes";
import { ArrowLeft, Loader2, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { api, isLoggedIn, type User } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const Settings = () => {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const { theme, setTheme } = useTheme();

  useEffect(() => {
    if (!isLoggedIn()) {
      navigate("/auth");
      return;
    }
    api.me().then(setUser).catch(() => navigate("/auth"));
  }, [navigate]);

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-accent" aria-label="Loading settings" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-reading-bg to-background">
      <header className="border-b border-border/50 bg-card/50 backdrop-blur">
        <div className="container mx-auto px-4 py-3">
          <Button variant="ghost" onClick={() => navigate("/dashboard")}>
            <ArrowLeft /> Library
          </Button>
        </div>
      </header>

      <main className="container mx-auto max-w-2xl px-4 py-8">
        <h1 className="mb-6 font-serif text-3xl font-bold text-primary">Settings</h1>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Account</CardTitle>
              <CardDescription>
                Signed in as <span className="font-medium text-foreground">{user.email}</span> since{" "}
                {new Date(user.created_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                variant="outline"
                onClick={() => {
                  api.signOut();
                  navigate("/");
                }}
              >
                <LogOut /> Sign out
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Appearance</CardTitle>
              <CardDescription>Dark mode is easier on the eyes for evening reading.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="inline-flex rounded-lg border p-1" role="radiogroup" aria-label="Theme">
                {[
                  { value: "light", label: "Light", icon: <Sun /> },
                  { value: "dark", label: "Dark", icon: <Moon /> },
                  { value: "system", label: "System", icon: <Monitor /> },
                ].map((t) => (
                  <Button
                    key={t.value}
                    variant="ghost"
                    size="sm"
                    role="radio"
                    aria-checked={theme === t.value}
                    onClick={() => setTheme(t.value)}
                    className={cn(theme === t.value && "bg-muted text-foreground")}
                  >
                    {t.icon} {t.label}
                  </Button>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
};

export default Settings;
