"""Identifier and hashing helpers."""

from __future__ import annotations

import hashlib
import os
import time


def new_id(prefix: str) -> str:
    """Sortable, collision-resistant id: ``<prefix>_<ms>_<random>``."""
    return f"{prefix}_{int(time.time() * 1000):013d}_{os.urandom(4).hex()}"


def content_hash(*parts: bytes | str) -> str:
    """Stable hash used for model-call dedup and evidence identity."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else part.encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def dedup_key(subject_id: str, event_type: str, bucket: str) -> str:
    """Idempotency key so a replay re-run does not double-count (v5 04)."""
    return f"{subject_id}:{event_type}:{bucket}"
