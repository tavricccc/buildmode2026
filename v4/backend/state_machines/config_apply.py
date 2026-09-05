"""Configuration apply state machine.

draft → validating → testing → applying → applied
                                   ↘ conflict (409)
                                   ↘ requires_restart
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigApplyContext:
    base_version: str | None
    current_version: str | None
    validation_errors: tuple[str, ...]
    test_failures: tuple[str, ...]
    requires_restart: bool = False


def config_apply_transition(ctx: ConfigApplyContext) -> str:
    if ctx.validation_errors:
        return "validation_failed"
    if ctx.base_version and ctx.current_version and ctx.base_version != ctx.current_version:
        return "conflict"
    if ctx.test_failures:
        return "test_failed"
    if ctx.requires_restart:
        return "applied_restart_required"
    return "applied"
