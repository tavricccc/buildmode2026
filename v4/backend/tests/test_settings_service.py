"""Settings service tests (optimistic concurrency + rollback)."""

from __future__ import annotations

import pytest

from v4.backend.realtime.broadcaster import RealtimeBroadcaster
from v4.backend.services.settings_service import SettingsError, SettingsService


@pytest.mark.asyncio
async def test_draft_then_apply_roundtrip(app_settings) -> None:
    service = SettingsService(broadcaster=RealtimeBroadcaster())
    draft = await service.draft({"fall": {"min_confidence": 0.65}}, base_version=None)
    assert draft["draft_id"].startswith("drf_")
    applied = await service.apply(draft["draft_id"], base_version="", confirm=True)
    assert applied["status"] in {"applied", "applied_restart_required"}
    assert applied["version_id"].startswith("cfg_")


@pytest.mark.asyncio
async def test_apply_without_base_version_conflicts(app_settings) -> None:
    service = SettingsService(broadcaster=RealtimeBroadcaster())
    await service.active_version()  # warm cache
    draft = await service.draft({"fall": {"min_confidence": 0.5}}, base_version=None)
    with pytest.raises(SettingsError) as excinfo:
        await service.apply(draft["draft_id"], base_version="bogus", confirm=True)
    assert excinfo.value.code == "CONFIG_VERSION_CONFLICT"


@pytest.mark.asyncio
async def test_high_risk_patch_requires_confirmation(app_settings) -> None:
    service = SettingsService(broadcaster=RealtimeBroadcaster())
    draft = await service.draft({"fall": {"min_confidence": 0.5}}, base_version=None)
    assert draft["requires_confirmation"] is True
    result = await service.apply(draft["draft_id"], base_version="", confirm=False)
    assert result["status"] == "requires_confirmation"


@pytest.mark.asyncio
async def test_rollback_creates_new_version(app_settings) -> None:
    service = SettingsService(broadcaster=RealtimeBroadcaster())
    draft = await service.draft({"fall": {"min_confidence": 0.5}}, base_version=None)
    await service.apply(draft["draft_id"], base_version="", confirm=True)
    versions = await service.list_versions()
    target = versions[0]["id"]
    result = await service.rollback(target)
    assert result["version_id"] != target
    assert result["rolled_back_from"] == target
