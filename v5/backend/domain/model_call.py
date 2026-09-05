"""Model-call provenance (v5 02 §Data, v5 00 item 10).

Every request to L2 or L3 leaves one of these behind, whether it
succeeded, was repaired, or failed. ``response_text`` is stored *after*
secret redaction, because providers echo request context into error
bodies and that is a realistic way for an API key to reach SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import Layer
from .ids import new_id
from .timeutil import iso


@dataclass
class ModelCall:
    call_id: str = field(default_factory=lambda: new_id("call"))
    layer: str = Layer.l2_gemini.value
    provider: str = ""
    model: str = ""
    purpose: str = ""
    prompt_version: str = ""
    schema_version: str = ""
    status: str = "ok"  # ok | repaired | invalid | failed
    latency_ms: int = 0
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    attempts: int = 1
    error_code: str | None = None
    error_message: str | None = None
    input_hash: str = ""
    #: redacted, truncated model output kept for the audit trail
    response_text: str | None = None
    evidence_id: str | None = None
    created_at: str = field(default_factory=iso)

    @property
    def succeeded(self) -> bool:
        return self.status in {"ok", "repaired"}

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
