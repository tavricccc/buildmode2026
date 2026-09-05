"""Secret service tests (write-only fingerprint)."""

from __future__ import annotations

import json

from v4.backend.services.secret_service import SecretService


def test_set_and_metadata(tmp_path) -> None:
    svc = SecretService(path=tmp_path / "secrets.json")
    meta = svc.set("telegram_bot_token", "secret")
    assert meta.configured is True
    assert len(meta.fingerprint_suffix) == 4
    on_disk = json.loads((tmp_path / "secrets.json").read_text())
    assert "secret" not in json.dumps(on_disk) or on_disk["telegram_bot_token"]["value"] == "secret"
    # The metadata API must never expose the raw value.
    again = svc.metadata("telegram_bot_token")
    assert again.fingerprint_suffix == meta.fingerprint_suffix


def test_clear_removes_entry(tmp_path) -> None:
    svc = SecretService(path=tmp_path / "secrets.json")
    svc.set("api_key", "x")
    cleared = svc.clear("api_key")
    assert cleared.configured is False
    assert svc.metadata("api_key").configured is False


def test_metadata_returns_unconfigured_for_missing(tmp_path) -> None:
    svc = SecretService(path=tmp_path / "secrets.json")
    meta = svc.metadata("missing")
    assert meta.configured is False
    assert meta.fingerprint_suffix == ""
