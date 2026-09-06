import { ROOT, checkFfmpeg, findPython, frontendBuilt, frontendInstalled, run } from "./lib";

/**
 * The single user entry point (docs/04_SETUP_DEPLOY_VERIFY.md).
 *
 * Two things it deliberately does NOT do: download a model, and create a
 * Python virtualenv. The first is forbidden by the spec; the second is
 * unnecessary because the backend imports only the standard library. So
 * a fresh clone reaches the Setup UI with nothing more than Python 3.11+.
 */
const args = process.argv.slice(2);
const dev = args.includes("--dev");
const passthrough = args.filter((arg) => arg !== "--dev");

const python = await findPython();

if (!checkFfmpeg()) {
  console.warn(
    "⚠️  ffmpeg was not found on PATH.\n" +
    "   The API and Setup UI still start, but frame ingest, clip encoding and the\n" +
    "   L1 detectors all need it. Install it before running a source.\n",
  );
}

if (dev) {
  if (!frontendInstalled()) {
    console.log("→ installing frontend dependencies…");
    await run(["bun", "install"], { cwd: `${ROOT}/frontend` });
  }
  console.log("→ starting the Vite dev server on http://localhost:5173");
  Bun.spawn(["bun", "run", "dev"], { cwd: `${ROOT}/frontend`, stdout: "inherit", stderr: "inherit" });
} else if (!frontendBuilt()) {
  if (frontendInstalled()) {
    console.log("→ building the Dashboard bundle…");
    await run(["bun", "run", "build"], { cwd: `${ROOT}/frontend` });
  } else {
    console.log(
      "→ the Dashboard bundle is not built. The API still works; run\n" +
      "  `cd frontend && bun install && bun run build`, or `bun run dev` for hot reload.\n",
    );
  }
}

const backend = Bun.spawn([python, "-m", "backend", ...passthrough], {
  cwd: ROOT, stdout: "inherit", stderr: "inherit", stdin: "inherit",
});

const stop = () => { backend.kill(); };
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
process.exit(await backend.exited);
