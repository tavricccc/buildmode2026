"""Health scenario service stub.

Applies the four documented Fake Health scenarios (``normal``,
``elevated_hr``, ``low_spo2``, ``inactive``). Each scenario writes a
small set of health samples so the Dashboard has something to show.
"""

from __future__ import annotations

import time

from ..domain.ids import new_id
from ..domain.time import isoformat, utc_now


_SCENARIOS: dict[str, list[dict]] = {
    "normal": [
        {"metric": "heart_rate", "value_num": 72, "unit": "bpm"},
        {"metric": "spo2", "value_num": 98, "unit": "%"},
        {"metric": "steps_today", "value_num": 2200, "unit": "steps"},
    ],
    "elevated_hr": [
        {"metric": "heart_rate", "value_num": 112, "unit": "bpm"},
        {"metric": "spo2", "value_num": 96, "unit": "%"},
        {"metric": "steps_today", "value_num": 1200, "unit": "steps"},
    ],
    "low_spo2": [
        {"metric": "heart_rate", "value_num": 95, "unit": "bpm"},
        {"metric": "spo2", "value_num": 89, "unit": "%"},
        {"metric": "steps_today", "value_num": 800, "unit": "steps"},
    ],
    "inactive": [
        {"metric": "heart_rate", "value_num": 70, "unit": "bpm"},
        {"metric": "spo2", "value_num": 97, "unit": "%"},
        {"metric": "steps_today", "value_num": 120, "unit": "steps"},
    ],
}


class HealthScenarioService:
    def __init__(self, subject_id: str) -> None:
        self._subject_id = subject_id

    def apply(self, scenario: str) -> dict:
        from ..repos.health_repo import HealthRepo
        from ..repos.session import session_scope

        rows = _SCENARIOS.get(scenario, _SCENARIOS["normal"])
        ts = isoformat(utc_now())
        async def _run():
            async with session_scope() as session:
                repo = HealthRepo(session)
                for row in rows:
                    await repo.insert(
                        sample_id=new_id("samp"),
                        subject_id=self._subject_id,
                        metric=row["metric"],
                        measured_at=ts,
                        created_at=ts,
                        value_num=row.get("value_num"),
                        unit=row.get("unit"),
                        source="fake",
                    )
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Fire-and-forget; the API will read after the call returns.
                loop.create_task(_run())
            else:
                loop.run_until_complete(_run())
        except RuntimeError:
            asyncio.run(_run())
        return {"scenario": scenario, "samples": rows, "applied_at": ts}

    def list_scenarios(self) -> list[str]:
        return list(_SCENARIOS.keys())
