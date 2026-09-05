import { spawnSync } from "node:child_process";
const result = spawnSync(process.env.CARE_PYTHON || "python", ["-m", "unittest", "discover", "-s", "backend/tests", "-p", "test_*.py", "-v"], { stdio: "inherit", env: process.env });
process.exit(result.status ?? 1);
