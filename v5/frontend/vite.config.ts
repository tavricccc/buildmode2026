import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend serves `dist/` in production, so the dev server proxies the
// API and the WebSocket rather than the frontend knowing two origins.
const BACKEND = process.env.CARE_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: true },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND.replace(/^http/, "ws"), ws: true },
    },
  },
});
