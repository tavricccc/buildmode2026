import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const httpsEnabled = ["1", "true", "yes", "on"].includes((process.env.HTTPS || "false").toLowerCase());
const backendPort = process.env.BACKEND_PORT || "8000";
const backendProtocol = httpsEnabled ? "https" : "http";
const backendWsProtocol = httpsEnabled ? "wss" : "ws";
const httpsOptions = httpsEnabled ? { key: readFileSync(process.env.HTTPS_KEY_FILE || "../certs/lan.key"), cert: readFileSync(process.env.HTTPS_CERT_FILE || "../certs/lan.crt") } : undefined;

export default defineConfig({
  plugins: [react()],
  server: { port: Number(process.env.FRONTEND_PORT || 5173), host: process.env.FRONTEND_HOST || "127.0.0.1", https: httpsOptions, proxy: { "/api": { target: `${backendProtocol}://127.0.0.1:${backendPort}`, secure: false }, "/ws": { target: `${backendWsProtocol}://127.0.0.1:${backendPort}`, ws: true, secure: false } } },
});
