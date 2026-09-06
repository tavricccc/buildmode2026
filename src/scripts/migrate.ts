import { ROOT, findPython, run } from "./lib";

const python = await findPython();
const code = await run([python, "-c",
  "from backend.config import AppConfig\n" +
  "from backend.store import Database, migrate\n" +
  "config = AppConfig(); config.ensure_dirs()\n" +
  "db = Database(config.db_path)\n" +
  "applied = migrate(db)\n" +
  "print(f'database: {config.db_path}')\n" +
  "print('applied: ' + (', '.join(applied) if applied else 'nothing — already current'))\n",
], { cwd: ROOT });
process.exit(code);
