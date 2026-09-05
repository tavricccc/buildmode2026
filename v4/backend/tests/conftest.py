"""Shared pytest fixtures for the v4 backend."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncIterator

import pytest_asyncio

from v4.backend.repos.session import dispose_engine, init_engine, run_migrations
from v4.backend.settings import AppSettings


@pytest_asyncio.fixture
async def app_settings(tmp_path: Path) -> AsyncIterator[AppSettings]:
    settings = AppSettings(
        db_path=tmp_path / "v4.sqlite",
        secret_store_path=tmp_path / "secrets.json",
        media_root=tmp_path / "captures",
        stub_enabled=False,
    )
    settings.media_root.mkdir(parents=True, exist_ok=True)
    await init_engine(settings)
    await run_migrations(settings)
    try:
        yield settings
    finally:
        await dispose_engine()
