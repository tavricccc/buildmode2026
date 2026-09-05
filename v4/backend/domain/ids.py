"""ID generation.

Prefixes match the v3 event envelope contract (e.g. ``evt_``, ``evd_``) so
audit tooling that already understands v3 can also parse v4 audit trails.
"""

from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Return a new ULID-shaped id with the given prefix.

    The random portion is a 16-hex-character slice — short enough for
    readability in logs, long enough (64 bits) to avoid practical collision.
    """
    return f"{prefix}_{uuid.uuid4().hex[:16]}"
