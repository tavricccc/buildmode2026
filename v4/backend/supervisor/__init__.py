"""Placeholder for the local runtime supervisor (v4 11).

The supervisor manages one or more local OpenAI-compatible runtimes
(llama.cpp / vLLM / Ollama). The actual launcher lands in a later
commit; this file declares the protocol so the rest of the
codebase can depend on it.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LocalRuntime(Protocol):
    async def start(self, model_id: str) -> dict[str, Any]: ...
    async def stop(self) -> None: ...
    def health(self) -> dict[str, Any]: ...
