"""Event repository tests."""

from __future__ import annotations

import pytest

from v4.backend.repos.event_repo import EventRepo
from v4.backend.repos.session import session_scope


@pytest.mark.asyncio
async def test_upsert_event_then_lookup_by_dedup(app_settings) -> None:
    async with session_scope() as session:
        repo = EventRepo(session)
        await repo.upsert(
            event_id="evt_1",
            subject_id="resident_demo",
            event_type="fall",
            status="candidate",
            occurred_at="2026-09-05T00:00:00Z",
            confidence=0.7,
            dedup_key="sha256:dedup",
            schema_version="event.v1",
            created_at="2026-09-05T00:00:00Z",
            updated_at="2026-09-05T00:00:00Z",
        )
        await session.flush()
        found = await repo.find_by_dedup("sha256:dedup")
    assert found is not None
    assert found.event_type == "fall"


@pytest.mark.asyncio
async def test_list_filtered_by_type(app_settings) -> None:
    async with session_scope() as session:
        repo = EventRepo(session)
        await repo.upsert(
            event_id="evt_2",
            subject_id="resident_demo",
            event_type="hydration",
            status="confirmed",
            occurred_at="2026-09-05T00:00:00Z",
            confidence=0.8,
            dedup_key="sha256:dedup2",
            schema_version="event.v1",
            created_at="2026-09-05T00:00:00Z",
            updated_at="2026-09-05T00:00:00Z",
        )
        await session.flush()
        only_hydration = await repo.list_filtered(event_type="hydration")
    assert all(e.event_type == "hydration" for e in only_hydration)
