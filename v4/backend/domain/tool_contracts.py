"""Logical-agent tool contract.

A logical agent calls only typed tools (never arbitrary SQL, never
arbitrary file paths, never secret values). The contract lives in
``domain/`` because it is shared between agents and the policy gateway.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AgentTool(Protocol):
    """A typed, read-only tool exposed to a logical agent."""

    name: str

    async def __call__(self, **kwargs: Any) -> Any:  # pragma: no cover - structural
        ...
