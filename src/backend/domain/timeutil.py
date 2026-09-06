"""Time helpers. All persisted timestamps are UTC ISO-8601 with ``Z``."""

from __future__ import annotations

from datetime import datetime, timezone


def now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def iso(ms: int | None = None) -> str:
    ts = now_ms() if ms is None else ms
    return (
        datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def day_key(ms: int | None = None) -> str:
    return iso(ms)[:10]


def parse_iso(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
