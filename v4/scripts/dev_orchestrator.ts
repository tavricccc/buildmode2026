#!/usr/bin/env bun
/**
 * `bun run dev` — start the backend with reload-friendly settings and
 * the Vite dev server. Used for local development.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dir, "..");
const venv = resolve(root, ".venv");
const py = process.platform === "win32"
  ? (existsSync(venv) ? `${venv}\\Scripts\\python.exe` : "python")
  : (existsSync(venv) ? `${venv}/bin/python` : "python");

const backend = spawn(py, ["-m", "v4.backend"], { cwd: root, env: process.env, stdio: "inherit" });
const frontend = spawn("bun", ["--cwd", resolve(root, "frontend"), "run", "dev"], {
  cwd: root,
  env: process.env,
  stdio: "inherit",
});

process.on("SIGINT", () => { backend.kill(); frontend.kill(); process.exit(0); });
process.on("SIGTERM", () => { backend.kill(); frontend.kill(); process.exit(0); });
