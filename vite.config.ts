import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig({
  server: {
    host: "::",
    port: 5173,
    // `npm run dev` talks to the API started by docker compose (host port 8100)
    proxy: {
      "/api": { target: process.env.VITE_API_PROXY ?? "http://localhost:8100", changeOrigin: true },
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
