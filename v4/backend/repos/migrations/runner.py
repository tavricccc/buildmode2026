"""Migration runner.

A tiny, file-numbered migration runner. Files live in
``repos/migrations/`` with the pattern ``NN_*.sql``. The runner
applies them in order inside a transaction, recording each
``filename`` in a ``schema_migrations`` table.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


logger = logging.getLogger(__name__)


_FILENAME_RE = re.compile(r"^(\d{2,})_.+\.sql$")


def _discover(migrations_dir: Path) -> list[Path]:
    if not migrations_dir.exists():
        return []
    files = sorted(p for p in migrations_dir.glob("*.sql") if _FILENAME_RE.match(p.name))
    return files


class MigrationRunner:
    def __init__(self, engine: AsyncEngine, migrations_dir: Path) -> None:
        self._engine = engine
        self._dir = migrations_dir

    async def _ensure_table(self) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        filename TEXT PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
            )

    async def _applied(self) -> set[str]:
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text("SELECT filename FROM schema_migrations"))).all()
        return {row[0] for row in rows}

    async def apply_pending(self) -> list[str]:
        await self._ensure_table()
        already = await self._applied()
        applied: list[str] = []
        for path in _discover(self._dir):
            if path.name in already:
                continue
            sql = path.read_text(encoding="utf-8")
            non_comment_lines = [
                line for line in sql.splitlines() if not line.strip().startswith("--")
            ]
            cleaned_sql = "\n".join(non_comment_lines)
            statements = [s.strip() for s in cleaned_sql.split(";") if s.strip()]
            async with self._engine.begin() as conn:
                for stmt in statements:
                    await conn.execute(text(stmt))
                await conn.execute(
                    text(
                        "INSERT INTO schema_migrations (filename, applied_at) VALUES (:fn, :ts)"
                    ),
                    {"fn": path.name, "ts": _now()},
                )
            applied.append(path.name)
            logger.info("migration applied", extra={"file": path.name})
        return applied


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
