"""WebSocket message envelope tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from v4.backend.realtime.messages import WSMessage, all_message_types


def test_all_message_types_contains_v4_additions() -> None:
    types = set(all_message_types())
    for required in {
        "system.status", "event.created", "model.activated",
        "model.install.progress", "model.probe.completed",
        "endpoint.updated", "settings.applied", "settings.rollback.completed",
    }:
        assert required in types


def test_ws_message_envelope() -> None:
    msg = WSMessage(
        message_id="msg_1",
        type="settings.applied",
        occurred_at="2026-09-05T00:00:00Z",
        payload={"version_id": "cfg_1"},
    )
    assert msg.schema_version == "realtime.v1"
    assert msg.payload["version_id"] == "cfg_1"


def test_ws_message_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        WSMessage(
            message_id="msg_1",
            type="not.a.real.type",
            occurred_at="2026-09-05T00:00:00Z",
        )
