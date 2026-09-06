"""SQLite connection handling and migrations (docs/02_DATA_AND_POLICY.md, docs/04_SETUP_DEPLOY_VERIFY.md).

Notes that are decisions rather than boilerplate:

* WAL journal mode, because the pipeline writes on a worker thread while
  the HTTP layer reads on request threads. Without WAL those readers
  block behind every window write.
* One connection per thread. ``sqlite3`` connections are not safe to
  share across threads, and a single shared lock would serialise the API
  behind the pipeline.
* Each migration is applied in one transaction, with its
  ``schema_migrations`` row written inside that same transaction, so a
  half-applied file cannot leave a live install in a state no version
  describes. The BEGIN/COMMIT is written into the script rather than
  wrapped around it, because ``executescript`` commits any open
  transaction before it starts.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()

    # -- connections -----------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=15.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA busy_timeout = 15000")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- queries ---------------------------------------------------------

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self.connect().execute(sql, tuple(params)))

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        rows = self.connect().execute(sql, tuple(params)).fetchone()
        return rows

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._write_lock:
            cursor = self.connect().execute(sql, tuple(params))
            return cursor.rowcount

    def execute_many(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self._write_lock:
            self.connect().executemany(sql, [tuple(r) for r in rows])

    def transaction(self):
        """Context manager wrapping a write batch in BEGIN/COMMIT."""
        return _Transaction(self)


class _Transaction:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self.db._write_lock.acquire()
        self._conn = self.db.connect()
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        assert self._conn is not None
        try:
            if exc_type is None:
                self._conn.execute("COMMIT")
            else:
                self._conn.execute("ROLLBACK")
        finally:
            self.db._write_lock.release()
        return False


def migrate(db: Database, migrations_dir: Path | None = None) -> list[str]:
    """Apply pending migrations in filename order. Returns what was applied."""
    directory = migrations_dir or MIGRATIONS_DIR
    conn = db.connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}

    performed: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        name = path.name.replace("'", "''")
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{sql}\n"
            f"INSERT INTO schema_migrations(name) VALUES ('{name}');\n"
            "COMMIT;"
        )
        with db._write_lock:
            try:
                conn.executescript(script)
            except Exception:
                conn.execute("ROLLBACK")
                raise
        performed.append(path.name)
    return performed
