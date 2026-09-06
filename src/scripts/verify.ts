import { ROOT, checkFfmpeg, findPython, frontendInstalled, run } from "./lib";

const python = await findPython();
let failures = 0;

console.log("→ python: compile check");
failures += (await run([python, "-m", "compileall", "-q", "backend"])) === 0 ? 0 : 1;

console.log("\n→ python: unit tests");
failures += (await run([python, "-m", "unittest", "discover", "-s", "backend/tests", "-t", "."])) === 0 ? 0 : 1;

if (frontendInstalled()) {
  console.log("\n→ frontend: typecheck");
  failures += (await run(["bun", "run", "typecheck"], { cwd: `${ROOT}/frontend` })) === 0 ? 0 : 1;
} else {
  console.log("\n→ frontend: skipped (run `bun install` in frontend/ to enable the typecheck)");
}

console.log(`\n→ ffmpeg: ${checkFfmpeg() ? "found" : "MISSING — ingest and clip encoding will not work"}`);

console.log(failures === 0 ? "\n✅ verify passed" : `\n❌ verify failed (${failures} step(s))`);
process.exit(failures === 0 ? 0 : 1);
