"""Setup service stub (v4 06).

Reports basic environment readiness: Python version, sqlite version,
whether ffmpeg is on PATH, free disk. The full camera / mic probe
arrives in a later commit.
"""

from __future__ import annotations

import platform
import shutil
import sqlite3
from pathlib import Path

from ..settings import AppSettings


class SetupService:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def status(self) -> dict:
        return {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "sqlite": sqlite3.sqlite_version,
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "media_root": str(self._settings.media_root),
            "media_root_exists": Path(self._settings.media_root).exists(),
            "db_path": str(self._settings.db_path),
            "stub_openai": {
                "enabled": self._settings.stub_enabled,
                "port": self._settings.stub_port,
            },
        }

    def prerequisites(self) -> list[dict]:
        items = [
            {"name": "python", "ok": True, "detail": platform.python_version()},
            {"name": "ffmpeg", "ok": shutil.which("ffmpeg") is not None, "detail": shutil.which("ffmpeg") or "missing"},
            {"name": "sqlite", "ok": True, "detail": sqlite3.sqlite_version},
        ]
        return items
