"""Auditable status-report assembly from stored care and social-work records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .domain.timeutil import now_ms


REPORT_TYPES = {"daily_status", "follow_up", "case_summary"}

# Social workers need a useful care handoff, not a replay of somebody's home.
# Keep this allow-list deliberately small.  New signals must be added here as
# an abstract status before they can appear in a report.
_MEDICATION_KEYS = {
    "medication_status", "medication_adherence", "medication_adherence_status",
    "medications_status", "medications_taken", "medication_taken", "meds_taken",
}
_EXERCISE_KEYS = {
    "exercise_status", "exercise_adherence", "activity_status", "activity_level",
    "physical_activity_status", "steps_status",
}
_SLEEP_KEYS = {
    "sleep_status", "sleep_regular", "sleep_regularity", "routine_status",
    "routine_irregular", "sleep_irregular", "sleep_disruption",
}
_DIET_KEYS = {
    "diet_status", "nutrition_status", "meal_status", "appetite_status",
    "diet_regular", "nutrition_regular",
}
_SOCIAL_KEYS = {
    "social_status", "social_engagement", "social_interaction",
    "communication_status", "social_contact_status",
}
_NORMAL_VALUES = {
    "ok", "normal", "regular", "stable", "adherent", "taken", "completed",
    "adequate", "sufficient", "未見異常", "正常", "規律", "穩定", "有",
}
_WARNING_VALUES = {
    "warning", "watch", "attention", "abnormal", "irregular", "missed",
    "low", "insufficient", "inadequate", "not_taken", "not_adherent",
    "需要確認", "異常", "不規律", "不足", "未服用",
}


def _key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _status(value: Any) -> str | None:
    """Map a structured source value to a non-sensitive public status."""
    if isinstance(value, bool):
        return "未見異常" if value else "需要進一步確認"
    if isinstance(value, (int, float)):
        # Numeric values are never shown.  Only an explicitly bounded adherence
        # value is interpreted, and the threshold is intentionally conservative.
        return "未見異常" if 0.8 <= float(value) <= 1.0 else "需要進一步確認"
    normalized = _key(value)
    if normalized in _NORMAL_VALUES:
        return "未見異常"
    if normalized in _WARNING_VALUES:
        return "需要進一步確認"
    return None


def _status_for_key(name: str, value: Any) -> str | None:
    result = _status(value)
    # These fields encode a problem when truthy, unlike adherence/status fields.
    if _key(name) in {"sleep_irregular", "routine_irregular", "sleep_disruption"}:
        if result == "未見異常":
            return "需要進一步確認"
        if result == "需要進一步確認":
            return "未見異常"
    return result


def _metric_status(health: list[dict[str, Any]], keys: set[str]) -> str:
    for item in health:
        if _key(item.get("metric")) not in keys:
            continue
        result = _status_for_key(str(item.get("metric", "")), item.get("value"))
        if result:
            return result
    return "資料不足"


def _observer_metric_status(observer_runs: list[dict[str, Any]], keys: set[str]) -> str:
    for run in observer_runs:
        metrics = run.get("metrics") or {}
        for name, value in metrics.items():
            if _key(name) not in keys:
                continue
            result = _status_for_key(str(name), value)
            if result:
                return result
    return "資料不足"


def _metric_score(health: list[dict[str, Any]], keys: set[str], status: str) -> int:
    for item in health:
        name = _key(item.get("metric"))
        if name not in keys:
            continue
        value = item.get("value")
        if isinstance(value, (int, float)) and 0 <= float(value) <= 1:
            if name in {"sleep_irregular", "routine_irregular", "sleep_disruption"}:
                value = 1 - float(value)
            return max(1, min(10, round(float(value) * 9 + 1)))
    return _score(status)


def _observer_metric_score(observer_runs: list[dict[str, Any]], keys: set[str], status: str) -> int:
    for run in observer_runs:
        for name, value in (run.get("metrics") or {}).items():
            normalized = _key(name)
            if normalized not in keys:
                continue
            if isinstance(value, (int, float)) and 0 <= float(value) <= 1:
                if normalized in {"sleep_irregular", "routine_irregular", "sleep_disruption"}:
                    value = 1 - float(value)
                return max(1, min(10, round(float(value) * 9 + 1)))
    return _score(status)


def _score(status: str) -> int:
    """Convert an abstract status to a display-only 1-10 radar value."""
    return {"未見異常": 8, "需要進一步確認": 4, "資料不足": 5}.get(status, 5)


def _privacy_dimensions(
    health: list[dict[str, Any]], observer_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return four abstract dimensions permitted in a social report."""
    exercise = _metric_status(health, _EXERCISE_KEYS)
    if exercise == "資料不足":
        exercise = _observer_metric_status(observer_runs, _EXERCISE_KEYS)
    sleep = _metric_status(health, _SLEEP_KEYS)
    if sleep == "資料不足":
        sleep = _observer_metric_status(observer_runs, _SLEEP_KEYS)
    diet = _metric_status(health, _DIET_KEYS)
    if diet == "資料不足":
        diet = _observer_metric_status(observer_runs, _DIET_KEYS)
    social = _metric_status(health, _SOCIAL_KEYS)
    if social == "資料不足":
        social = _observer_metric_status(observer_runs, _SOCIAL_KEYS)
    sleep_score = _metric_score(health, _SLEEP_KEYS, sleep)
    diet_score = _metric_score(health, _DIET_KEYS, diet)
    exercise_score = _metric_score(health, _EXERCISE_KEYS, exercise)
    social_score = _metric_score(health, _SOCIAL_KEYS, social)
    if sleep == "資料不足":
        sleep_score = _observer_metric_score(observer_runs, _SLEEP_KEYS, sleep)
    if diet == "資料不足":
        diet_score = _observer_metric_score(observer_runs, _DIET_KEYS, diet)
    if exercise == "資料不足":
        exercise_score = _observer_metric_score(observer_runs, _EXERCISE_KEYS, exercise)
    if social == "資料不足":
        social_score = _observer_metric_score(observer_runs, _SOCIAL_KEYS, social)
    return [
        {"key": "sleep", "name": "睡眠狀態", "status": sleep, "score": sleep_score},
        {"key": "diet", "name": "飲食狀態", "status": diet, "score": diet_score},
        {"key": "exercise", "name": "運動狀態", "status": exercise, "score": exercise_score},
        {"key": "social", "name": "社交狀態", "status": social, "score": social_score},
    ]


def _privacy_summary(
    events: list[dict[str, Any]], observations: list[dict[str, Any]],
    observer_runs: list[dict[str, Any]], health: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a role-safe summary without copying source prose or raw values."""
    dimensions = _privacy_dimensions(health, observer_runs)
    medication = _metric_status(health, _MEDICATION_KEYS)
    warnings = [item for item in dimensions if item["status"] == "需要進一步確認"]
    if medication == "需要進一步確認":
        warnings.append({"name": "用藥狀態", "status": medication})
    follow_up: list[str] = []

    if any(event.get("event_type") == "fall" for event in events):
        follow_up.append("請人工確認近期安全相關訊號及目前處置狀態。")
    for item in warnings:
        follow_up.append(f"請進一步確認{item['name']}是否需要照護介入或補充紀錄。")
    if records:
        follow_up.append("已有社工服務紀錄，請由承辦人確認是否需要納入後續處遇。")
    if not observations and not observer_runs:
        follow_up.append("目前結構化觀察不足，請人工確認近期整體狀態。")
    if not follow_up:
        follow_up.append("目前未形成需升級的抽象警示，依原照護流程持續觀察。")

    if any(item["status"] == "需要進一步確認" for item in warnings) or any(
        event.get("event_type") == "fall" for event in events
    ):
        overall = "需要關注"
    elif any(item["status"] != "資料不足" for item in dimensions) and (observations or observer_runs or health):
        overall = "整體穩定"
    else:
        overall = "資料不足"

    return {
        "overall": overall,
        "dimensions": dimensions,
        "medication_status": medication,
        "follow_up": list(dict.fromkeys(follow_up)),
    }


def _stamp(value: int) -> str:
    return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M")


def auto_generate_social_work_log(
    ctx: Any,
    window_hours: int = 24,
    record_type: str = "case_note",
    author: str = "AI 社工助理 (事件自動彙整)",
    save_to_records: bool = True,
    save_to_reports: bool = True,
) -> dict[str, Any]:
    """Create a privacy-safe social-work handoff from bounded source data.

    The source records remain available to the controlled audit layer.  This
    function is the public-data boundary: it must not copy utterances, source
    descriptions, exact measurements, completion counts, or model scores.
    """
    from .care_logging import CareLogger

    window_hours = max(1, min(int(window_hours), 720))
    ended = now_ms()
    started = ended - window_hours * 3600_000

    # 1. Fetch system events within the time window
    all_events = ctx.repos.list_events(limit=200)
    events = [e for e in all_events if int(e.get("occurred_at_ms", 0)) >= started]
    falls = [e for e in events if e.get("event_type") == "fall"]
    hydration_events = [e for e in events if e.get("event_type") == "hydration"]

    # 2. Fetch visual observations (L2) and observer runs (L3/Observer)
    all_obs = ctx.repos.list_observations(ctx.config.subject_id, limit=200)
    observations = [o for o in all_obs if int(o.get("observed_at_ms", 0)) >= started]

    all_obs_runs = ctx.repos.list_observer_runs(ctx.config.subject_id, limit=50)
    observer_runs = [r for r in all_obs_runs if int(r.get("window_ended_at_ms", 0)) >= started]

    # 3. Fetch health metrics
    health = ctx.repos.latest_health(ctx.config.subject_id)

    # 4. Fetch existing human social work records in the window
    existing_notes = [
        r for r in ctx.repos.list_social_work_records(ctx.config.subject_id, started, limit=50)
        if "事件自動彙整" not in (r.get("tags") or [])
    ]

    # 5. Assemble the role-safe journal.  Keep the familiar SOAP headings for
    # workflow compatibility, but each section contains only an abstraction.
    privacy = _privacy_summary(events, observations, observer_runs, health, existing_notes)
    title = f"【社工日誌・隱私摘要】（過去 {window_hours} 小時）"
    lines = [
        "長照機構社工日誌（隱私摘要）",
        f"【期間】最近 {window_hours} 小時",
        f"【產出人員】{author}",
        "【資料原則】僅保留整體狀態、抽象警示與待確認事項；不呈現逐筆生活事件、逐字互動、精確數值、完成次數或模型分數。",
        "",
        "一、S｜主觀與服務接觸 (Subjective)",
    ]
    lines.append("- 不展開住民逐字內容或生活起居細節；如需補充，請由社工依權限查閱並人工確認。")
    lines.append("- " + ("已有服務接觸紀錄，請承辦人確認其後續處遇意義。" if existing_notes else "目前沒有可供社工覆核的服務接觸摘要。"))

    lines.extend([
        "",
        "二、O｜整體狀態與抽象警示 (Objective)",
        f"- 整體狀態：{privacy['overall']}。",
    ])
    lines.append("- 保留的抽象警示：")
    for dimension in privacy["dimensions"]:
        lines.append(f"  · {dimension['name']}：{dimension['score']}/10（{dimension['status']}）。")
    lines.append(f"  · 用藥狀態警示：{privacy['medication_status']}。")

    lines.extend([
        "",
        "三、A｜資料導向評估 (Assessment)",
        "- 本摘要只反映可用的結構化照護訊號，不構成醫療診斷、量表分數或對住民日常的完整描述。",
        "- 未提供的項目維持為資料不足，不以推測補寫成正常或異常。",
        "",
        "四、P｜需要進一步確認的事項 (Plan)",
    ])
    lines.extend(f"{index}. {item}" for index, item in enumerate(privacy["follow_up"], start=1))
    lines.append("- 本篇為系統彙整初稿，請由具權限的社工人工覆核後再作服務決定。")

    body_text = "\n".join(lines)

    sources = {
        "event_ids": [item["event_id"] for item in events],
        "fall_ids": [item["event_id"] for item in falls],
        "hydration_ids": [item["event_id"] for item in hydration_events],
        "observation_ids": [item["observation_id"] for item in observations],
        "observer_run_ids": [item["observer_run_id"] for item in observer_runs],
        "health_signal_count": len(health),
        "social_work_record_ids": [item["record_id"] for item in existing_notes],
        "privacy_dimensions": privacy["dimensions"],
        "medication_status": privacy["medication_status"],
        "window_hours": window_hours,
    }

    record_id = ""
    if save_to_records:
        record_id = ctx.repos.save_social_work_record(
            subject_id=ctx.config.subject_id,
            record_type=record_type if record_type in {"visit", "phone", "case_note", "follow_up", "resource_referral"} else "case_note",
            occurred_at_ms=ended,
            author=author,
            content=body_text,
            tags=["事件自動彙整", "社工日誌", f"{window_hours}小時", "SOAP格式"],
        )

    report_id = ""
    if save_to_reports:
        report_id = ctx.repos.save_status_report(
            subject_id=ctx.config.subject_id,
            report_type="daily_status",
            window_start_ms=started,
            window_end_ms=ended,
            title=title,
            body=body_text,
            sources=sources,
        )

    # Structured logging via CareLogger
    CareLogger.get_instance(ctx.repos).info(
        "reporting",
        f"已成功自動彙整產生社工日誌（涵蓋事件 {len(events)} 筆、觀察 {len(observations)} 筆、跌倒 {len(falls)} 筆）",
        {"record_id": record_id, "report_id": report_id, "window_hours": window_hours, "events_count": len(events)},
    )

    return {
        "record_id": record_id,
        "report_id": report_id,
        "title": title,
        "body": body_text,
        "window_hours": window_hours,
        "window_start_ms": started,
        "window_end_ms": ended,
        "sources": sources,
        "stats": {
            "warning_count": len([item for item in privacy["dimensions"] if item["status"] == "需要進一步確認"]) + int(privacy["medication_status"] == "需要進一步確認"),
            "follow_up_count": len(privacy["follow_up"]),
            "privacy_safe": True,
        },
    }


def build_status_report(ctx: Any, report_type: str, days: int = 7) -> dict[str, Any]:
    if report_type not in REPORT_TYPES:
        raise ValueError("unknown report type")
    days = max(1, min(int(days), 90))
    ended = now_ms()
    started = ended - days * 86_400_000
    records = ctx.repos.list_social_work_records(ctx.config.subject_id, started, 200)
    events = [event for event in ctx.repos.list_events(limit=200)
              if int(event.get("occurred_at_ms", 0)) >= started]
    observations = [item for item in ctx.repos.list_observations(ctx.config.subject_id, 200)
                    if int(item.get("observed_at_ms", 0)) >= started]
    observer = [item for item in ctx.repos.list_observer_runs(ctx.config.subject_id, 50)
                if int(item.get("window_ended_at_ms", 0)) >= started]
    health = ctx.repos.latest_health(ctx.config.subject_id)

    label = {"daily_status": "日常狀態報告", "follow_up": "追蹤狀態報告", "case_summary": "個案摘要報告"}[report_type]
    privacy = _privacy_summary(events, observations, observer, health, records)
    lines = [
        f"【{label}・隱私摘要】",
        f"期間：最近 {days} 天。",
        "資料原則：只呈現整體狀態、運動／用藥／作息的抽象警示與待確認事項。",
        "不呈現逐筆生活事件、逐字互動、精確數值、完成次數、個人化模型分數或原始觀察描述。",
        "",
        "一、S｜服務接觸狀態",
    ]
    if records:
        lines.append("- 本期間有社工服務紀錄，內容不在此展開；請承辦人確認是否需納入後續處遇。")
    else:
        lines.append("- 此期間沒有可供覆核的社工服務摘要；本段不以模型推測補足。")

    lines.extend(["", "二、O｜整體狀態與抽象警示", f"- 整體狀態：{privacy['overall']}。", "- 保留的抽象警示："])
    lines.extend(f"  · {item['name']}：{item['score']}/10（{item['status']}）。" for item in privacy["dimensions"])
    lines.append(f"  · 用藥狀態警示：{privacy['medication_status']}。")
    lines.extend([
        "",
        "三、A｜資料導向評估",
        "- 本報告只依可用的結構化照護訊號彙整，不構成醫療診斷、量表分數或完整生活紀錄。",
        "- 未提供的項目維持為資料不足，不以推測補寫成正常或異常。",
        "",
        "四、P｜需要進一步確認的事項",
    ])
    lines.extend(f"{index}. {item}" for index, item in enumerate(privacy["follow_up"], start=1))
    lines.append("- 請由具權限的社工人工覆核後，再決定是否需要服務介入。")

    sources = {
        "social_work_record_ids": [item["record_id"] for item in records],
        "event_ids": [item["event_id"] for item in events],
        "observation_ids": [item["observation_id"] for item in observations],
        "observer_run_ids": [item["observer_run_id"] for item in observer],
        "health_signal_count": len(health),
        "privacy_dimensions": privacy["dimensions"],
        "medication_status": privacy["medication_status"],
    }
    return {"report_type": report_type, "window_start_ms": started, "window_end_ms": ended,
            "title": label, "body": "\n".join(lines), "sources": sources}
