"""Write-only secret store (v5 03 §Setup/Settings, v5 04 §Secrets).

Requirements this exists to enforce, not merely to document:

* A secret can be written and *used*, but never read back over the API.
  ``describe()`` is the only thing any route is allowed to serialise.
* Nothing lands in Git: the store file lives under ``data/`` and is
  created 0600.
* ``redact()`` is applied to every outbound log line and error string, so
  a provider echoing a key back in a 4xx body cannot leak it into SQLite.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Iterable

#: Every secret the system knows about. Anything not listed is rejected,
#: so a typo cannot silently create an unreachable second key.
SECRET_KEYS = (
    "GEMINI_API_KEY",
    "MINIMAX_API_KEY",
    "RTSP_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
)

_MIN_REDACT_LEN = 8


class SecretStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._cache: dict[str, str] = {}
        self._load()

    # -- persistence -----------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self._cache = {k: v for k, v in raw.items() if k in SECRET_KEYS and isinstance(v, str)}

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass  # Windows / WSL-mounted filesystems may not support this.
        tmp.replace(self.path)

    # -- access ----------------------------------------------------------

    def set(self, key: str, value: str) -> None:
        if key not in SECRET_KEYS:
            raise KeyError(f"unknown secret: {key!r}")
        with self._lock:
            if value:
                self._cache[key] = value
            else:
                self._cache.pop(key, None)
            self._flush()

    def get(self, key: str) -> str | None:
        """Backend-internal use only. Never serialise the result."""
        if key not in SECRET_KEYS:
            raise KeyError(f"unknown secret: {key!r}")
        with self._lock:
            value = self._cache.get(key)
        # An env var is a legitimate source (Docker, CI) but never a sink:
        # we read from it and never write back to it.
        return value or os.environ.get(key) or None

    def configured(self, key: str) -> bool:
        return bool(self.get(key))

    def describe(self) -> dict[str, dict[str, object]]:
        """The *only* shape an API response may contain (v5 03)."""
        out: dict[str, dict[str, object]] = {}
        for key in SECRET_KEYS:
            value = self.get(key)
            out[key] = {
                "configured": bool(value),
                "source": "store" if self._cache.get(key) else ("env" if value else "none"),
                "length": len(value) if value else 0,
            }
        return out

    def known_values(self) -> Iterable[str]:
        for key in SECRET_KEYS:
            value = self.get(key)
            if value and len(value) >= _MIN_REDACT_LEN:
                yield value

    def redact(self, text: str) -> str:
        """Strip every configured secret from a string bound for a log or DB."""
        if not text:
            return text
        for value in self.known_values():
            text = text.replace(value, "***redacted***")
        return text
