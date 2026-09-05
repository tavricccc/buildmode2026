"""Model call repository audit tests."""

from __future__ import annotations

import pytest

from v4.backend.repos.model_call_repo import ModelCallRepo
from v4.backend.repos.session import session_scope


@pytest.mark.asyncio
async def test_record_persists_v4_columns(app_settings) -> None:
    async with session_scope() as session:
        repo = ModelCallRepo(session)
        repo.record(
            call_id="mcall_1",
            endpoint_id="local-stub",
            deployment_type="local",
            model_id="vision-stub",
            capability="vision",
            input_hash="sha256:x",
            prompt_version="vision-events.v1",
            schema_version="event.v1",
            status="success",
            latency_ms=120,
            tokens_in=16,
            tokens_out=8,
            error_code=None,
            response_json="{}",
            created_at="2026-09-05T00:00:00Z",
            config_version="cfg_1",
        )
        await session.flush()
        recent = await repo.list_recent(limit=5)
    assert any(c.id == "mcall_1" for c in recent)
    record = next(c for c in recent if c.id == "mcall_1")
    assert record.model_endpoint_id == "local-stub"
    assert record.capability == "vision"
    assert record.config_version == "cfg_1"
