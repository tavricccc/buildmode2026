"""Migration 01: ensure all 17 expected tables exist after applying."""

from __future__ import annotations

from sqlalchemy import text

from v4.backend.repos.session import engine


EXPECTED_TABLES = {
    "evidence", "model_calls", "events", "event_evidence",
    "hydration_sessions", "health_samples", "analyses", "actions",
    "app_logs", "transcripts", "memories", "runtime_state", "tool_calls",
    "daily_summaries", "observer_findings", "notification_deliveries",
    "model_endpoints", "installed_models", "config_versions",
    "active_models", "schema_migrations",
}


async def test_all_tables_present(app_settings) -> None:
    eng = engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).all()
    names = {r[0] for r in rows}
    missing = EXPECTED_TABLES - names
    assert not missing, f"missing tables: {missing}"


async def test_model_calls_has_v4_columns(app_settings) -> None:
    eng = engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(text("PRAGMA table_info(model_calls)"))).all()
    cols = {r[1] for r in rows}
    assert {"model_endpoint_id", "config_version", "capability"}.issubset(cols)
