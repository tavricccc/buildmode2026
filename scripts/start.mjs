import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

if (existsSync(".env")) {
  for (const line of readFileSync(".env", "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (match && process.env[match[1]] === undefined) process.env[match[1]] = match[2].replace(/^['"]|['"]$/g, "");
  }
}

const python = process.env.CARE_PYTHON || (existsSync(".venv/Scripts/python.exe") ? ".venv/Scripts/python.exe" : (process.platform === "win32" ? "python.exe" : "python3"));
const bindHost = process.env.BIND_HOST || process.env.BACKEND_HOST || "127.0.0.1";
const backendPort = process.env.BACKEND_PORT || "8000";
const frontendHost = process.env.FRONTEND_HOST || bindHost;
const frontendPort = process.env.FRONTEND_PORT || "5173";
const httpsEnabled = ["1", "true", "yes", "on"].includes((process.env.HTTPS || "false").toLowerCase());
const certFile = resolve(process.env.HTTPS_CERT_FILE || "certs/lan.crt");
const keyFile = resolve(process.env.HTTPS_KEY_FILE || "certs/lan.key");
if (httpsEnabled && (!existsSync(certFile) || !existsSync(keyFile))) {
  console.error(`[care-agent] HTTPS certificate files are required: ${certFile} and ${keyFile}`);
  process.exit(1);
}
process.env.HTTPS_CERT_FILE = certFile;
process.env.HTTPS_KEY_FILE = keyFile;
const backendArgs = ["-m", "uvicorn", "backend.app:app", "--host", bindHost, "--port", backendPort];
if (httpsEnabled) backendArgs.push("--ssl-keyfile", keyFile, "--ssl-certfile", certFile);
const backend = spawn(python, backendArgs, { stdio: "inherit", env: process.env });
let frontend;
if (existsSync("frontend/node_modules") || existsSync("node_modules/vite")) {
  const frontendCommand = `npm --prefix frontend run dev -- --host ${frontendHost} --port ${frontendPort}`;
  frontend = process.platform === "win32"
    ? spawn("cmd.exe", ["/d", "/s", "/c", frontendCommand], { stdio: "inherit", env: process.env })
    : spawn("npm", ["--prefix", "frontend", "run", "dev", "--", "--host", "127.0.0.1"], { stdio: "inherit", env: process.env });
} else {
  console.warn("[care-agent] frontend dependencies are not installed; run npm install at the repository root.");
}
const stop = () => { backend.kill("SIGTERM"); frontend?.kill("SIGTERM"); };
process.on("SIGINT", stop); process.on("SIGTERM", stop);
backend.on("exit", (code) => { if (code && code !== 0) process.exitCode = code; frontend?.kill("SIGTERM"); });
