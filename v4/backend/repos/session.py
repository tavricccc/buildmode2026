"""Database engine and session lifecycle.

The engine is created once per process (see ``init_engine``) and
disposed on shutdown. ``session_scope`` is a small async context
manager that handles commit/rollback for write paths.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import AppSettings
from .migrations.runner import MigrationRunner


logger = logging.getLogger(__name__)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def init_engine(settings: AppSettings) -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        return
    db_path = settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{db_path}"

    _engine = create_async_engine(url, future=True, echo=False)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)

    # WAL + foreign keys for each new connection.
    @event.listens_for(_engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("PRAGMA busy_timeout = 5000;")
        cur.close()


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is None:
        return
    await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def run_migrations(settings: AppSettings) -> None:
    assert _engine is not None, "engine not initialised"
    runner = MigrationRunner(engine=_engine, migrations_dir=Path(__file__).parent / "migrations")
    applied = await runner.apply_pending()
    if applied:
        logger.info("migrations applied", extra={"files": applied})


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    assert _sessionmaker is not None, "engine not initialised"
    session = _sessionmaker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session() -> AsyncSession:
    assert _sessionmaker is not None, "engine not initialised"
    return _sessionmaker()


def engine() -> AsyncEngine:
    assert _engine is not None, "engine not initialised"
    return _engine
