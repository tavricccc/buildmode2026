"""Secret service (v4 13).

The service stores secrets in a small JSON file under the data
directory. It never returns the raw value: callers only see
``{"configured": true, "updated_at": ..., "fingerprint_suffix": "abcd"}``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretMetadata:
    name: str
    configured: bool
    updated_at: str
    fingerprint_suffix: str


class SecretService:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({})

    def set(self, name: str, value: str) -> SecretMetadata:
        if not value:
            raise ValueError("secret value must be non-empty")
        data = self._read()
        data[name] = {
            "value": value,
            "updated_at": _now(),
            "fingerprint": _fingerprint(value),
        }
        self._write(data)
        return self.metadata(name)

    def clear(self, name: str) -> SecretMetadata:
        data = self._read()
        data.pop(name, None)
        self._write(data)
        return SecretMetadata(
            name=name,
            configured=False,
            updated_at=_now(),
            fingerprint_suffix="",
        )

    def metadata(self, name: str) -> SecretMetadata:
        data = self._read()
        entry = data.get(name)
        if entry is None:
            return SecretMetadata(name=name, configured=False, updated_at="", fingerprint_suffix="")
        return SecretMetadata(
            name=name,
            configured=True,
            updated_at=entry["updated_at"],
            fingerprint_suffix=entry["fingerprint"][-4:],
        )

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def _read(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _write(self, data: dict) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
        try:
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover - platform specific
            pass


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
