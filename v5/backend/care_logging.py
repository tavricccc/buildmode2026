"""Unified system-wide logging infrastructure for Care Agent v5.

Ensures every layer of the system (HTTP API, L1 perception, L2 vision,
L3 escalation, resident interaction, social work reporting, observer scheduler)
logs to both:
1. SQLite `app_logs` table (queryable via /api/logs and displayed in UI)
2. `care-system.log` file in the v5 root directory (viewable in audit logs)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
LOG_FILE_PATH = ROOT_DIR / "care-system.log"
MAX_LOG_BYTES = 10 * 1024 * 1024  # 10MB


class CareLogger:
    _instance: "CareLogger | None" = None
    _lock = threading.Lock()

    def __init__(self, repos: Any = None, log_file: Path | None = None) -> None:
        self.repos = repos
        self.log_file = log_file or LOG_FILE_PATH
        self._file_lock = threading.Lock()
        self._ensure_file()

    @classmethod
    def get(cls) -> "CareLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = CareLogger()
            return cls._instance

    @classmethod
    def get_instance(cls, repos: Any = None) -> "CareLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = CareLogger(repos=repos)
            elif repos is not None and cls._instance.repos is None:
                cls._instance.repos = repos
            return cls._instance

    @classmethod
    def set_repos(cls, repos: Any) -> None:
        with cls._lock:
            if cls._instance is None:
                cls._instance = CareLogger(repos=repos)
            else:
                cls._instance.repos = repos

    def _ensure_file(self) -> None:
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            if not self.log_file.exists():
                self.log_file.touch(exist_ok=True)
        except Exception:  # noqa: BLE001
            pass

    def log(self, level: str, source: str, message: str, context: dict[str, Any] | None = None) -> None:
        level_lower = level.lower().strip()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        ctx_str = f" | {json.dumps(context, ensure_ascii=False)}" if context else ""
        formatted_line = f"[{timestamp}] [{level_lower.upper():<5}] [{source}] {message}{ctx_str}\n"

        # 1. Write to SQLite app_logs if repos is bound
        if self.repos is not None:
            try:
                self.repos.log(level_lower, source, message, context or {})
            except Exception:  # noqa: BLE001
                pass

        # 2. Append to care-system.log file
        with self._file_lock:
            try:
                if self.log_file.exists() and self.log_file.stat().st_size > MAX_LOG_BYTES:
                    backup = self.log_file.with_name(f"care-system.{int(time.time())}.log")
                    self.log_file.rename(backup)
                with open(self.log_file, "a", encoding="utf-8", errors="replace") as f:
                    f.write(formatted_line)
            except Exception:  # noqa: BLE001
                pass

    def info(self, source: str, message: str, context: dict[str, Any] | None = None) -> None:
        self.log("info", source, message, context)

    def warn(self, source: str, message: str, context: dict[str, Any] | None = None) -> None:
        self.log("warn", source, message, context)

    def error(self, source: str, message: str, context: dict[str, Any] | None = None) -> None:
        self.log("error", source, message, context)

    def debug(self, source: str, message: str, context: dict[str, Any] | None = None) -> None:
        self.log("debug", source, message, context)


class CareLoggingHandler(logging.Handler):
    """Bridges standard Python logging into CareLogger."""

    def __init__(self, logger: CareLogger) -> None:
        super().__init__()
        self.care_logger = logger

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level_map = {
                logging.DEBUG: "debug",
                logging.INFO: "info",
                logging.WARNING: "warn",
                logging.ERROR: "error",
                logging.CRITICAL: "error",
            }
            level = level_map.get(record.levelno, "info")
            msg = self.format(record)
            source = record.name or "python"
            self.care_logger.log(level, source, msg)
        except Exception:  # noqa: BLE001
            pass


def setup_system_logging(repos: Any = None) -> CareLogger:
    logger = CareLogger.get()
    if repos is not None:
        logger.repos = repos

    root = logging.getLogger()
    if not any(isinstance(h, CareLoggingHandler) for h in root.handlers):
        handler = CareLoggingHandler(logger)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    return logger
