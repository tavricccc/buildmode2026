import { ROOT, findPython } from "./lib";

const python = await findPython();
const args = process.argv.slice(2);
if (!args.length) {
  console.error("usage: bun run debug:seed --days 45 --profile mixed --seed 20260906");
  process.exit(2);
}

const child = Bun.spawn([python, "-m", "backend.debug.cli", ...args], {
  cwd: ROOT,
  stdout: "inherit",
  stderr: "inherit",
  stdin: "inherit",
  env: { ...process.env, CARE_MODE: "debug" },
});
process.exit(await child.exited);
