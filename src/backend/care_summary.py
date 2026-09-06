from __future__ import annotations

from typing import Any

from .domain.enums import EventType
from .domain.timeutil import now_ms


def build_care_summary(ctx: Any) -> dict[str, Any]:
    source = ctx.source.health() if ctx.source else {"running": False, "lifecycle": "stopped"}
    fall = ctx.repos.open_event(ctx.config.subject_id, EventType.fall)
    observer_rows = ctx.repos.list_observer_runs(ctx.config.subject_id, 1)
    observer = observer_rows[0] if observer_rows else None
    analysis = None
    policy_status = "not_requested"
    delivery_status = "not_sent"

    if fall:
        row = ctx.db.query_one(
            "SELECT * FROM analyses WHERE event_id=? ORDER BY created_at DESC LIMIT 1",
            (fall["event_id"],))
        analysis = dict(row) if row is not None else None
        action = ctx.db.query_one(
            "SELECT * FROM actions WHERE event_id=? ORDER BY created_at DESC LIMIT 1",
            (fall["event_id"],))
        if action is not None:
            policy_status = ("suppressed" if action["suppressed"]
                             else "authorised" if action["kind"] == "notify_telegram"
                             else "dashboard_only")
            delivery = ctx.db.query_one(
                "SELECT status FROM notification_deliveries WHERE action_id=? "
                "ORDER BY created_at DESC LIMIT 1", (action["action_id"],))
            delivery_status = str(delivery["status"]) if delivery is not None else "not_sent"

    urgency = "none"
    state = "stable"
    headline = "目前沒有需要介入的警訊"
    reasons: list[str] = []
    next_step = "依原排程持續觀察"
    confidence = float((observer or {}).get("confidence", 0) or 0)
    completeness = float((observer or {}).get("data_completeness", 0) or 0)
    limitations: list[str] = []

    if fall:
        status = str(fall["status"])
        confidence = float(fall.get("confidence", confidence) or confidence)
        if status == "confirmed":
            urgency, state = "immediate", "intervention_required"
            headline = "確認有跌倒事件，需要立即複核"
            next_step = "請依機構流程立即確認住民狀況"
        elif status == "recovering":
            urgency, state = "watch", "recovering"
            headline = "住民已恢復動作，仍在追蹤"
            next_step = "請確認是否已安全起身，並持續觀察"
        else:
            urgency, state = "watch", "attention"
            headline = "偵測到疑似跌倒，需要留意"
            next_step = "請查看事件影像並確認住民狀況"
        reasons.append(f"跌倒事件目前為 {status}")

    risk = str((analysis or {}).get("risk_level") or "none")
    recommendation = str((analysis or {}).get("recommendation") or "")
    if fall and risk == "critical":
        urgency, state = "immediate", "intervention_required"
        headline = "AI 強烈建議立即介入"
        reasons.append("L3 深度覆核評估為最高風險")
    elif fall and risk == "high" and urgency != "immediate":
        urgency, state = "today", "attention"
        headline = "AI 建議今日介入複核"
        reasons.append("L3 深度覆核評估為高風險")
    if recommendation == "suggest_caregiver_notification":
        reasons.append("AI 建議聯繫照護人員")

    if not fall and observer:
        if observer["status"] == "anomaly":
            urgency, state = "today", "attention"
            headline = str(observer["headline"])
            next_step = "請在今日照護流程中複核這項變化"
        elif observer["status"] == "attention":
            urgency, state = "watch", "attention"
            headline = str(observer["headline"])
            next_step = "持續記錄並比較下一次觀察結果"
        elif observer["status"] == "insufficient_evidence":
            urgency, state = "unknown", "insufficient_evidence"
            headline = "資料不足，暫時無法形成照護判讀"
            next_step = "請先確認影像來源與觀察資料是否持續更新"
            limitations.append("結構化觀察不足")

    lifecycle = str(source.get("lifecycle", "running" if source.get("running") else "stopped"))
    if not source.get("running") and urgency == "none":
        urgency, state = "unknown", "source_unavailable"
        headline = "目前沒有即時影像，無法確認最新狀況"
        next_step = "請檢查影像來源"
        limitations.append("錄影播放完成" if lifecycle == "completed" else "影像來源未啟動")

    return {
        "state": state,
        "urgency": urgency,
        "headline": headline,
        "reasons": reasons,
        "recommended_next_step": next_step,
        "confidence": round(confidence, 3),
        "data_completeness": round(completeness, 3),
        "policy_status": policy_status,
        "delivery_status": delivery_status,
        "generated_at_ms": now_ms(),
        "model": (analysis or {}).get("call_id"),
        "source_event_id": fall.get("event_id") if fall else None,
        "limitations": limitations,
        "source_lifecycle": lifecycle,
        "runtime_mode": ctx.config.runtime_mode,
    }
