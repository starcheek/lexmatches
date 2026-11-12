import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";

// The app used to register a service worker that cached authenticated /api responses by URL (two users
// on one browser could see each other's data). It is gone; remove it and its caches from old installs.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker
    .getRegistrations()
    .then((regs) => regs.forEach((r) => void r.unregister()))
    .catch(() => undefined);
}
if ("caches" in window) {
  caches
    .keys()
    .then((keys) => keys.filter((k) => k.startsWith("lexmatches-")).forEach((k) => void caches.delete(k)))
    .catch(() => undefined);
}

createRoot(document.getElementById("root")!).render(<App />);
