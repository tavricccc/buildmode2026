"""Replay service stub (v4 03 / v3 05).

Full integration with the live ReplaySource arrives in a later
commit. This round exposes a typed surface that the API can wire
up immediately.
"""

from __future__ import annotations

from pathlib import Path

from ..settings import AppSettings


class ReplayService:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._state: dict[str, str] = {"status": "stopped", "video_id": ""}

    def list(self) -> list[dict]:
        if not self._settings.replay_manifest_path.exists():
            return []
        import json
        data = json.loads(self._settings.replay_manifest_path.read_text(encoding="utf-8"))
        return data.get("replays", [])

    def status(self) -> dict:
        return dict(self._state)

    def load(self, video_id: str) -> dict:
        self._state["video_id"] = video_id
        return {"ok": True, "video_id": video_id}

    def start(self) -> dict:
        self._state["status"] = "playing"
        return dict(self._state)

    def pause(self) -> dict:
        self._state["status"] = "paused"
        return dict(self._state)

    def reset(self) -> dict:
        self._state = {"status": "stopped", "video_id": ""}
        return dict(self._state)
