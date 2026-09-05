"""Local runtime supervisor (placeholder; v4 11)."""

from typing import Any


class LocalRuntimeSupervisor:
    def __init__(self) -> None:
        self._running: dict[str, dict[str, Any]] = {}

    async def start(self, model_id: str) -> dict[str, Any]:
        self._running[model_id] = {
            "model_id": model_id,
            "status": "starting",
            "base_url": "",
        }
        return self._running[model_id]

    async def stop(self) -> None:
        self._running.clear()

    def health(self) -> dict[str, Any]:
        return {"running": list(self._running.keys())}
