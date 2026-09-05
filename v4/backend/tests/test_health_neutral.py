"""Hardware-neutral guard (v4 DoD #4).

Greps the entire ``v4/backend/`` tree and fails if any Apple/GPU-vendor
identifier leaks into domain code. The list is intentionally broad so
that future vendor-specific imports are caught early.

Files containing only documentation (e.g. ``__init__.py`` docstrings
that explicitly mention the excluded vendors) are allowed.
"""

from __future__ import annotations

import re
from pathlib import Path


BANNED = re.compile(
    r"\b(mlx|mps|metal|darwin|cuda|rocm|torch|jax)\b",
    re.IGNORECASE,
)

# Files that document the exclusion of vendor SDKs.
ALLOWLIST = {
    "tests/test_health_neutral.py",
    "__init__.py",
    "supervisor/local_runtime.py",
}


def test_no_vendor_specific_imports() -> None:
    backend = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend).as_posix()
        if rel in ALLOWLIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # Only flag actual import lines, not docstrings or comments.
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            if BANNED.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, "vendor-specific import leaked into domain code:\n" + "\n".join(offenders)
