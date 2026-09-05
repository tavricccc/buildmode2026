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

from typing import Any

from ..domain.enums import EscalationTrigger
from ..domain.l3_contract import EvidenceBundle
from ..domain.timeutil import day_key

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
    }
    return payload


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

    return {"day": target, "summary": summary, "baseline_7d": week, "baseline_30d": month,
            "changes": changes, "findings": findings, "narrative": narrative}


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
    return {"ok": True, **result.analysis.to_dict()}
