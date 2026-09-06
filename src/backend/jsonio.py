"""Tolerant JSON extraction for model replies.

Both providers are *asked* for bare JSON — Gemini via
``responseMimeType: application/json``, MiniMax via ``response_format``.
Neither guarantees it, and the failure modes are boringly consistent: a
markdown fence, a sentence of preamble, or a trailing comma. Recovering
from those here costs one function; treating them as schema violations
would burn the single repair attempt docs/01_PIPELINE.md allows on formatting noise
instead of on a genuine contract error.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


class JsonExtractionError(ValueError):
    pass


def extract_json(text: str) -> dict[str, Any]:
    """Return the first JSON object in ``text``, or raise."""
    if not text or not text.strip():
        raise JsonExtractionError("empty response")

    for candidate in _candidates(text):
        for attempt in (candidate, _TRAILING_COMMA.sub(r"\1", candidate)):
            try:
                parsed = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise JsonExtractionError(f"no JSON object found in {len(text)} chars")


def _candidates(text: str) -> list[str]:
    stripped = text.strip()
    out = [stripped]
    fenced = _FENCE.search(stripped)
    if fenced:
        out.append(fenced.group(1).strip())
    braced = _outermost_object(stripped)
    if braced:
        out.append(braced)
    return out


def _outermost_object(text: str) -> str | None:
    """Slice the first balanced ``{...}``, ignoring braces inside strings."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
