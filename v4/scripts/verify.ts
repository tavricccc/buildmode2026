#!/usr/bin/env bun
/**
 * `bun run verify` — run the backend's pytest suite and the frontend's
 * typecheck. Returns a non-zero exit code if either step fails.
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dir, "..");

const venv = resolve(root, ".venv");
const py = process.platform === "win32"
  ? (existsSync(venv) ? `${venv}\\Scripts\\python.exe` : "python")
  : (existsSync(venv) ? `${venv}/bin/python` : "python");

function step(name: string, cmd: string, args: string[]) {
  console.log(`\n[verify] running ${name}: ${cmd} ${args.join(" ")}`);
  const result = spawnSync(cmd, args, { cwd: root, stdio: "inherit" });
  if (result.status !== 0) {
    console.error(`[verify] ${name} failed with code ${result.status}`);
    process.exit(result.status ?? 1);
  }
}

step("pytest", py, ["-m", "pytest", "backend/tests", "-v"]);
step("frontend typecheck", "bun", ["--cwd", resolve(root, "frontend"), "run", "typecheck"]);
console.log("\n[verify] all green");
