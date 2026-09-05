#!/usr/bin/env bun
/**
 * `bun start` — boot the v4 backend (and stub OpenAI server) plus the
 * Vite frontend. Each process is launched as a detached child so the
 * orchestrator stays alive after the first run.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dir, "..");

function run(label: string, cmd: string, args: string[], env: Record<string, string> = {}) {
  const child = spawn(cmd, args, { cwd: root, env: { ...process.env, ...env }, stdio: "inherit" });
  child.on("exit", (code) => {
    if (code !== 0) {
      console.error(`[${label}] exited with code ${code}`);
    }
  });
  return child;
}

function ensureVenv(): string {
  const venv = resolve(root, ".venv");
  if (existsSync(venv)) return venv;
  console.log("[setup:backend] creating virtual environment at", venv);
  const result = spawn.sync("python", ["-m", "venv", venv], { stdio: "inherit" });
  if (result.status !== 0) {
    console.error("[setup:backend] failed to create venv");
    process.exit(result.status ?? 1);
  }
  const pip = process.platform === "win32" ? `${venv}\\Scripts\\pip.exe` : `${venv}/bin/pip`;
  const install = spawn.sync(pip, ["install", "-e", root], { stdio: "inherit" });
  if (install.status !== 0) {
    console.error("[setup:backend] pip install failed");
    process.exit(install.status ?? 1);
  }
  return venv;
}

function pythonBin(venv: string): string {
  return process.platform === "win32" ? `${venv}\\Scripts\\python.exe` : `${venv}/bin/python`;
}

const venv = ensureVenv();
const py = pythonBin(venv);

run("backend", py, ["-m", "v4.backend"]);
run("frontend", "bun", ["--cwd", resolve(root, "frontend"), "run", "dev"]);

process.on("SIGINT", () => process.exit(0));
process.on("SIGTERM", () => process.exit(0));
