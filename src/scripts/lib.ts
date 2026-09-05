import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Find a usable Python. docs/04_SETUP_DEPLOY_VERIFY.md requires a fresh clone to run without a
 * virtualenv step, so this looks for an interpreter rather than creating
 * an environment — the backend imports nothing outside the standard
 * library, which is what makes that possible.
 */
export async function findPython(): Promise<string> {
  const candidates = [process.env.CARE_PYTHON, "python3", "python"].filter(Boolean) as string[];
  for (const candidate of candidates) {
    const probe = Bun.spawnSync([candidate, "-c", "import sys; print(sys.version_info[:2])"], {
      cwd: ROOT, stdout: "pipe", stderr: "pipe",
    });
    if (probe.exitCode !== 0) continue;
    const text = new TextDecoder().decode(probe.stdout).trim();
    const match = text.match(/\((\d+),\s*(\d+)\)/);
    if (!match) continue;
    const [major, minor] = [Number(match[1]), Number(match[2])];
    if (major > 3 || (major === 3 && minor >= 11)) return candidate;
    console.error(`  ${candidate} is Python ${major}.${minor}; 3.11+ is required.`);
  }
  console.error(
    "\nNo suitable Python found. Install Python 3.11 or newer, or set CARE_PYTHON.\n" +
    "No packages need installing — the backend uses only the standard library.\n",
  );
  process.exit(1);
}

export function checkFfmpeg(): boolean {
  const probe = Bun.spawnSync(["ffmpeg", "-version"], { stdout: "pipe", stderr: "pipe" });
  return probe.exitCode === 0;
}

export function frontendBuilt(): boolean {
  return existsSync(join(ROOT, "frontend", "dist", "index.html"));
}

export function frontendInstalled(): boolean {
  return existsSync(join(ROOT, "frontend", "node_modules"));
}

export async function run(cmd: string[], options: { cwd?: string; label?: string } = {}): Promise<number> {
  const child = Bun.spawn(cmd, {
    cwd: options.cwd ?? ROOT,
    stdout: "inherit",
    stderr: "inherit",
    stdin: "inherit",
  });
  return await child.exited;
}
