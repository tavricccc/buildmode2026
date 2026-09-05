#!/usr/bin/env bun
/**
 * `bun run migrate` — create the venv (if missing) and apply the
 * initial SQL migration against the local SQLite file.
 */
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dir, "..");
const venv = resolve(root, ".venv");
const py = process.platform === "win32"
  ? (existsSync(venv) ? `${venv}\\Scripts\\python.exe` : "python")
  : (existsSync(venv) ? `${venv}/bin/python` : "python");

if (!existsSync(venv)) {
  console.log("[migrate] venv missing; running setup:backend first");
  const bootstrap = spawnSync("bash", [resolve(root, "scripts/bootstrap_venv.sh")], { stdio: "inherit" });
  if (bootstrap.status !== 0) process.exit(bootstrap.status ?? 1);
}

// The simplest way to run the migration is to import the backend and
// trigger run_migrations via the lifespan. For an explicit CLI we
// inline that here.
const code = `
import asyncio
from v4.backend.settings import AppSettings
from v4.backend.repos.session import init_engine, run_migrations, dispose_engine

async def main():
    settings = AppSettings.from_env()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    await init_engine(settings)
    await run_migrations(settings)
    await dispose_engine()
    print("migrations applied")

asyncio.run(main())
`;

const result = spawnSync(py, ["-c", code], { cwd: root, stdio: "inherit" });
if (result.status !== 0) process.exit(result.status ?? 1);
