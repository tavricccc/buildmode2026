"""Time helpers.

All timestamps in the v4 backend are stored in UTC ISO 8601 with millisecond
precision. Localisation happens at the edge (frontend) — domain code never
trusts a naive ``datetime``.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
