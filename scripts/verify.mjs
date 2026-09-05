import { spawnSync } from "node:child_process";
const defaultPython = process.platform === "win32" ? "python.exe" : "python3";
const result = spawnSync(process.env.CARE_PYTHON || defaultPython, ["-m", "unittest", "discover", "-s", "backend/tests", "-p", "test_*.py", "-v"], { stdio: "inherit", env: process.env });
process.exit(result.status ?? 1);
