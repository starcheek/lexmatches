import { lazy, Suspense, useEffect } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { initTracking, trackPage } from "@/lib/track";
import { ThemeProvider } from "next-themes";
import { Loader2 } from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SubscriptionProvider } from "@/contexts/SubscriptionContext";
import { queryClient } from "@/lib/queryClient";

// Route-level code splitting: the landing page does not download the reader, charts or pdf.js.
const Index = lazy(() => import("./pages/Index"));
const Auth = lazy(() => import("./pages/Auth"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Read = lazy(() => import("./pages/Read"));
const Progress = lazy(() => import("./pages/Progress"));
const Settings = lazy(() => import("./pages/Settings"));
const Admin = lazy(() => import("./pages/Admin"));
const NotFound = lazy(() => import("./pages/NotFound"));

const RouteFallback = () => (
  <div className="flex min-h-screen items-center justify-center bg-background">
    <Loader2 className="h-8 w-8 animate-spin text-accent" aria-label="Loading" />
  </div>
);

/** Usage analytics: starts the listeners once and reports every route change. Renders nothing. */
const Tracker = () => {
  const { pathname } = useLocation();
  useEffect(() => {
    initTracking();
    trackPage(pathname);
  }, [pathname]);
  return null;
};

const App = () => (
  <ThemeProvider attribute="class" defaultTheme="light" storageKey="lexmatches:theme" disableTransitionOnChange>
    <QueryClientProvider client={queryClient}>
      <SubscriptionProvider>
        <TooltipProvider delayDuration={300}>
          {/* bottom, above the reader's docked controls */}
          <Toaster position="bottom-center" offset={96} />
          <BrowserRouter>
            <Tracker />
            <Suspense fallback={<RouteFallback />}>
              <Routes>
                <Route path="/" element={<Index />} />
                <Route path="/auth" element={<Auth />} />
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/read/:bookId" element={<Read />} />
                <Route path="/progress" element={<Progress />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/admin" element={<Admin />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </TooltipProvider>
      </SubscriptionProvider>
    </QueryClientProvider>
  </ThemeProvider>
);

export default App;
