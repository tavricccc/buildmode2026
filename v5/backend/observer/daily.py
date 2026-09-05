"""Daily rollup and baseline comparison (v5 02 §Observer).

The cost rule is the interesting part. v5 02 says the observer may call
MiniMax "只有達設定變化門檻才呼叫，且只送 fixed-size summaries/aggregate".
So this module computes the whole day deterministically from SQLite, and
only when a metric has actually moved against its 7/30-day baseline does
it spend an L3 call — and then it sends numbers, never footage. A day of
video would be both ruinously expensive and no more informative than the
aggregates already are.
"""

from __future__ import annotations

import json
from typing import Any

from ..domain.enums import EscalationTrigger
from ..domain.l3_contract import EvidenceBundle
from ..domain.timeutil import day_key
from ..domain.timeutil import now_ms
from ..jsonio import JsonExtractionError, extract_json

#: Relative change against baseline that justifies spending an L3 call.
DEFAULT_CHANGE_THRESHOLD = 0.30


def compute_day(ctx: Any, day: str) -> dict[str, Any]:
    """Deterministic aggregates for one day. No model involved."""
    repos = ctx.repos
    hydration = repos.hydration_summary(day)

    rows = ctx.db.query(
        """SELECT COUNT(*) AS windows,
                  SUM(l2_outcome = 'skipped_l1') AS skipped,
                  SUM(l2_outcome IN ('called','heartbeat','forced_high_risk')) AS l2_calls,
                  SUM(l3_outcome IN ('called','degraded_text_only')) AS l3_calls,
                  SUM(l2_outcome = 'failed') AS l2_failures
           FROM pipeline_runs WHERE substr(created_at, 1, 10) = ?""",
        (day,),
    )
    counters = {k: (v or 0) for k, v in dict(rows[0]).items()} if rows else {}

    falls = ctx.db.query(
        """SELECT COUNT(*) AS n FROM events
           WHERE event_type='fall' AND status IN ('confirmed','recovering','resolved')
             AND substr(created_at, 1, 10) = ?""",
        (day,),
    )
    fall_count = falls[0]["n"] if falls else 0

    windows = counters.get("windows", 0)
    body = _body_observations(ctx, day)
    payload = {
        "day": day,
        "hydration_ml": hydration.get("total_ml", 0),
        "hydration_sessions": hydration.get("sessions", 0),
        "fall_events": fall_count,
        "l2_calls": counters.get("l2_calls", 0),
        "l2_skipped": counters.get("skipped", 0),
        "l2_failures": counters.get("l2_failures", 0),
        "l3_calls": counters.get("l3_calls", 0),
        "windows": windows,
        # What fraction of windows we actually looked at. A low value with a
        # healthy L1 means real saving; with an unhealthy L1 it means blind spots.
        "coverage_ratio": round(counters.get("l2_calls", 0) / windows, 4) if windows else 0.0,
        "skip_ratio": round(counters.get("skipped", 0) / windows, 4) if windows else 0.0,
        **body,
    }
    return payload


def _body_observations(ctx: Any, day: str) -> dict[str, Any]:
    """Summarise validated L2 observations already stored in SQLite.

    The model never receives database access. We parse the redacted, bounded
    observation payloads and expose only an allow-listed aggregate.
    """
    rows = ctx.db.query(
        """SELECT response_text FROM model_calls
           WHERE layer='l2_gemini' AND status IN ('ok','repaired')
             AND substr(created_at, 1, 10)=? AND response_text IS NOT NULL
           ORDER BY created_at DESC LIMIT 2048""",
        (day,),
    )
    observations: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = extract_json(str(row["response_text"]))
        except (JsonExtractionError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            observations.append(payload)

    posture_counts = {key: 0 for key in ("standing", "sitting", "lying", "crouching", "unknown")}
    motionless = 0
    active = 0
    confidences: list[float] = []
    for item in observations:
        fall = item.get("fall") if isinstance(item.get("fall"), dict) else {}
        posture = str(fall.get("posture", "unknown"))
        posture_counts[posture if posture in posture_counts else "unknown"] += 1
        is_motionless = bool(fall.get("motionless", False))
        motionless += int(is_motionless)
        active += int(bool(item.get("person_visible")) and not is_motionless)
        try:
            confidences.append(float(item.get("confidence", 0)))
        except (TypeError, ValueError):
            pass

    latest = observations[0] if observations else {}
    latest_fall = latest.get("fall") if isinstance(latest.get("fall"), dict) else {}
    total = len(observations)
    return {
        "observation_count": total,
        "posture_counts": posture_counts,
        "current_posture": str(latest_fall.get("posture", "unknown")),
        "current_motionless": bool(latest_fall.get("motionless", False)),
        "current_scene_summary": str(latest.get("scene_summary", ""))[:240],
        "current_confidence": round(float(latest.get("confidence", 0) or 0), 3),
        "motionless_ratio": round(motionless / total, 4) if total else 0.0,
        "activity_ratio": round(active / total, 4) if total else 0.0,
        "observation_confidence_avg": round(sum(confidences) / len(confidences), 3)
        if confidences else 0.0,
    }


def baseline(ctx: Any, day: str, window_days: int) -> dict[str, float]:
    rows = ctx.db.query(
        """SELECT AVG(hydration_ml) AS hydration_ml, AVG(hydration_sessions) AS hydration_sessions,
                  AVG(fall_events) AS fall_events, AVG(coverage_ratio) AS coverage_ratio
           FROM (SELECT * FROM daily_summaries WHERE day_key < ?
                 ORDER BY day_key DESC LIMIT ?)""",
        (day, window_days),
    )
    return {k: float(v or 0.0) for k, v in dict(rows[0]).items()} if rows else {}


def _relative_change(current: float, base: float) -> float:
    if base <= 0:
        return 1.0 if current > 0 else 0.0
    return abs(current - base) / base


def run_observer(ctx: Any, day: str | None = None,
                 threshold: float = DEFAULT_CHANGE_THRESHOLD) -> dict[str, Any]:
    started_at_ms = now_ms()
    target = day or day_key()
    summary = compute_day(ctx, target)
    ctx.repos.upsert_daily_summary(target, ctx.config.subject_id, summary)

    week = baseline(ctx, target, 7)
    month = baseline(ctx, target, 30)

    changes: dict[str, float] = {}
    for metric in ("hydration_ml", "hydration_sessions", "fall_events", "coverage_ratio"):
        change = _relative_change(float(summary.get(metric, 0)), week.get(metric, 0.0))
        if change >= threshold:
            changes[metric] = round(change, 3)

    findings: list[str] = []
    for metric, change in changes.items():
        direction = "up" if summary.get(metric, 0) > week.get(metric, 0.0) else "down"
        finding_id = ctx.repos.save_finding(
            subject_id=ctx.config.subject_id, day=target, kind=f"baseline_shift:{metric}",
            headline=f"{metric.replace('_', ' ')} is {direction} {change:.0%} against the 7-day baseline",
            detail=f"today={summary.get(metric)} · 7d={week.get(metric, 0):.1f} · 30d={month.get(metric, 0):.1f}",
            severity="warning" if metric == "fall_events" else "info",
            call_id=None,
            payload={"summary": summary, "baseline_7d": week, "baseline_30d": month},
        )
        findings.append(finding_id)

    narrative = None
    if changes and ctx.l3 is not None:
        narrative = _narrate(ctx, target, summary, week, month, changes)

    windows = int(summary.get("windows", 0) or 0)
    observations = int(summary.get("observation_count", 0) or 0)
    completeness = min(1.0, observations / max(1, int(summary.get("l2_calls", 0) or 0)))
    confidence = float(summary.get("current_confidence", 0) or 0)
    if windows == 0 or observations == 0:
        status, headline = "insufficient_evidence", "目前資料不足，無法形成身體狀況判讀"
    elif int(summary.get("fall_events", 0) or 0) > 0:
        status, headline = "anomaly", "觀察期間出現跌倒相關事件"
    elif changes:
        status, headline = "attention", "部分指標偏離個人近期基準"
    else:
        status, headline = "stable", "目前狀況穩定，未發現新的異常訊號"

    detail = (
        f"姿勢={summary.get('current_posture', 'unknown')} · "
        f"活動比例={float(summary.get('activity_ratio', 0)):.0%} · "
        f"飲水={float(summary.get('hydration_ml', 0)):.0f} ml · "
        f"分析 {observations} 筆結構化觀察"
    )
    call_id = narrative.get("call_id") if narrative and narrative.get("ok") else None
    observer_run_id = ctx.repos.save_observer_run(
        ctx.config.subject_id, started_at_ms, now_ms(), status, headline, detail,
        confidence, completeness, "l3_narrative" if call_id else "deterministic",
        call_id, summary, list(changes),
    )

    return {"day": target, "observer_run_id": observer_run_id, "status": status,
            "headline": headline, "summary": summary, "baseline_7d": week,
            "baseline_30d": month, "changes": changes, "findings": findings,
            "narrative": narrative}


def _narrate(ctx: Any, day: str, summary: dict[str, Any], week: dict[str, float],
             month: dict[str, float], changes: dict[str, float]) -> dict[str, Any] | None:
    """Spend one L3 call on aggregates only — never on footage."""
    bundle = EvidenceBundle(
        escalation_id=f"observer_{day}",
        trigger=EscalationTrigger.policy_second_opinion,
        reason_codes=["unusual_inactivity" if "coverage_ratio" in changes else "other"],
        l2_observation={"daily_summary": summary},
        event_state={"day": day, "changed_metrics": changes},
        clip=None,  # deliberate: aggregates are the whole payload
        aggregates={"baseline_7d": week, "baseline_30d": month},
    )
    result = ctx.l3.analyse(bundle, [], allow_text_only=True)
    ctx.repos.save_model_call(result.call)
    if not result.ok:
        return {"ok": False, "error": result.call.error_code}
    ctx.repos.save_finding(
        subject_id=ctx.config.subject_id, day=day, kind="observer_narrative",
        headline=result.analysis.interpretation[:200],
        detail=result.analysis.recommendation, severity="info",
        call_id=result.call.call_id, payload=result.analysis.to_dict(),
    )
    return {"ok": True, "call_id": result.call.call_id, **result.analysis.to_dict()}
