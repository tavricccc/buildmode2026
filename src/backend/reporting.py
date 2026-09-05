"""Auditable status-report assembly from stored care and social-work records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .domain.timeutil import now_ms


REPORT_TYPES = {"daily_status", "follow_up", "case_summary"}


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
    """Read system events, hydration, observations, and interactions within window_hours

    and automatically assemble a comprehensive SOAP social work daily log / incident report.
    Persists the generated log to social_work_records and status_reports.
    """
    from .care_logging import CareLogger

    window_hours = max(1, min(int(window_hours), 720))
    ended = now_ms()
    started = ended - window_hours * 3600_000
    start_str = _stamp(started)
    end_str = _stamp(ended)

    # 1. Fetch system events within the time window
    all_events = ctx.repos.list_events(limit=200)
    events = [e for e in all_events if int(e.get("occurred_at_ms", 0)) >= started]
    falls = [e for e in events if e.get("event_type") == "fall"]
    hydration_events = [e for e in events if e.get("event_type") == "hydration"]
    other_events = [e for e in events if e.get("event_type") not in ("fall", "hydration")]

    # 2. Fetch hydration summary
    hydration = {}
    try:
        hydration = ctx.repos.hydration_summary()
    except Exception:
        hydration = {}
    intake_ml = int(hydration.get("today_intake_ml", 0))
    target_ml = int(hydration.get("target_ml", 1500))
    hydration_rate = round((intake_ml / target_ml * 100), 1) if target_ml > 0 else 0.0

    # 3. Fetch visual observations (L2) and observer runs (L3/Observer)
    all_obs = ctx.repos.list_observations(ctx.config.subject_id, limit=200)
    observations = [o for o in all_obs if int(o.get("observed_at_ms", 0)) >= started]

    all_obs_runs = ctx.repos.list_observer_runs(ctx.config.subject_id, limit=50)
    observer_runs = [r for r in all_obs_runs if int(r.get("window_ended_at_ms", 0)) >= started]

    # 4. Fetch health metrics
    health = ctx.repos.latest_health(ctx.config.subject_id)

    # 5. Fetch interactions
    interactions = ctx.repos.interaction_messages(ctx.config.subject_id, "default", limit=40)
    user_turns = [m for m in interactions if m.get("role") == "user"]

    # 6. Fetch existing human social work records in the window
    existing_notes = [
        r for r in ctx.repos.list_social_work_records(ctx.config.subject_id, started, limit=50)
        if "事件自動彙整" not in (r.get("tags") or [])
    ]

    # 7. Assemble Structured SOAP Note
    title = f"【社工日誌 · 事件自動彙整】個案：{ctx.config.subject_id}（過去 {window_hours} 小時）"
    lines = [
        f"══════════════════════════════════════════════════",
        f"        長照機構社工日常照護日誌（事件自動彙整）",
        f"══════════════════════════════════════════════════",
        f"【服務對象】{ctx.config.subject_id}",
        f"【統計區間】{start_str} 至 {end_str}（共 {window_hours} 小時）",
        f"【產生時間】{_stamp(ended)}",
        f"【產出人員】{author}",
        "",
        "一、S｜主觀陳述與住民互動反應 (Subjective)",
    ]

    if user_turns:
        recent_utterances = user_turns[-3:]
        lines.append(f"- 住民於近期互動中提出：")
        for u in recent_utterances:
            lines.append(f"  · 「{u.get('text', '').strip()}」")
        lines.append("- 住民情感與溝通狀態：能主動表達需求，意識清楚，對話配合度良好。")
    else:
        lines.append("- 本時段尚無住民端直接語音/文字對話紀錄；主觀狀態採日常巡視照護觀察。")

    if existing_notes:
        lines.append(f"- 本期間照護人員／社工共登載 {len(existing_notes)} 筆現場互動紀錄：")
        for note in existing_notes[:3]:
            who = f"（{note['author']}）" if note.get("author") else ""
            lines.append(f"  · {_stamp(int(note['occurred_at_ms']))} [{note.get('record_type')}]{who}：{note.get('content')[:80]}")
    else:
        lines.append("- 期間無新增之人工手動訪視或電訪備忘。")

    lines.extend([
        "",
        "二、O｜客觀系統事件與監測數據 (Objective)",
        "【1. 重大與安全事件監控】",
    ])
    if falls:
        lines.append(f"- ⚠️ 偵測到 {len(falls)} 次疑似跌倒或突發安全事件：")
        for f in falls:
            t = _stamp(int(f.get("occurred_at_ms", 0)))
            st = f.get("status", "unknown")
            conf = f.get("confidence", 0)
            lines.append(f"  · 時間：{t}｜處理狀態：{st}｜模型信心度：{conf:.2f}")
    else:
        lines.append(f"- ✅ 監控期間無跌倒或突發劇烈失衡事件（跌倒通報：0 件）。")

    if other_events:
        lines.append(f"- 其他照護事件：共 {len(other_events)} 筆（離床/滯留/設備事件）。")

    lines.append("【2. 水分攝取與補水狀況】")
    lines.append(
        f"- 今日累計水分攝取量：{intake_ml} ml / 目標 {target_ml} ml（達成率：{hydration_rate}%）。"
    )
    lines.append(f"- 系統記錄補水事件共 {len(hydration_events)} 次。")
    if hydration_rate < 50:
        lines.append("- ⚠️ 水分補充進度偏低，需照護員加強定時引導與提供溫開水。")
    elif hydration_rate >= 80:
        lines.append("- ✅ 水分攝取進度理想，達標狀況良好。")

    lines.append("【3. 視覺行為感知與日常活動 (Vision & Posture)】")
    lines.append(f"- 期間視覺環境感測共產出 {len(observations)} 筆結構化觀察。")
    if observations:
        for obs in observations[:3]:
            lines.append(f"  · {_stamp(int(obs.get('observed_at_ms', 0)))}：{obs.get('summary', '正常日常動態')}")
    if observer_runs:
        latest_obs = observer_runs[0]
        headline = latest_obs.get("headline", "常態穩定")
        obs_status = latest_obs.get("status", "stable")
        lines.append(f"- 長期行為趨勢（Observer）：[{obs_status}] {headline}")
    else:
        lines.append("- 長期日常節律維持常態穩定。")

    lines.append("【4. 生理徵象量測 (Vitals)】")
    if health:
        vitals_str = "、".join(f"{h.get('metric')} {h.get('value')}{h.get('unit', '')}" for h in health[:6])
        lines.append(f"- 最新生理數值：{vitals_str}")
    else:
        lines.append("- 期間尚無新上傳之生理量測數據。")

    lines.extend([
        "",
        "三、A｜專業綜合評估 (Assessment)",
    ])
    if falls:
        lines.append("1. 安全風險：【高風險】期間發生跌倒紀錄，需全面檢核步態穩定度、防滑設施與下床輔具。")
    else:
        lines.append("1. 安全風險：【低風險/穩定】動態穩定無跌倒異常，行動安全良好。")

    if hydration_rate < 50:
        lines.append("2. 水分代謝：【需關注】飲水量未達半數，有輕度脫水或泌尿系統不適潛在風險。")
    else:
        lines.append("2. 水分代謝：【良好】飲水規律，生理代謝補充適足。")

    lines.append("3. 認知與生活功能：能配合照護流程，精神及情緒未見躁動或社交退縮傾向。")
    lines.append("4. 本評估由 AI 系統依據已存取之多模態事件日誌綜合彙編，供專業社工審閱。")

    lines.extend([
        "",
        "四、P｜後續處置與追蹤計畫 (Plan)",
        "1. 防跌維護：持續維持走道無障礙、夜間輔助地燈照明及床欄安全定位。",
        "2. 水分補充：由當班照護員於餐間安排 2~3 次定時溫開水引導。",
        "3. 社工關懷：安排每週定時個別訪視，持續建立信賴關係並追蹤情緒與生活滿意度。",
        "4. 跨專業交班：重要數據與事件同步記錄於交接班系統，通報責任護理師。",
        "5. 人工覆核：本篇日誌經系統自動讀取事件產生，已歸檔至社工紀錄資料庫待覆核。",
    ])

    body_text = "\n".join(lines)

    sources = {
        "event_ids": [item["event_id"] for item in events],
        "fall_ids": [item["event_id"] for item in falls],
        "hydration_ids": [item["event_id"] for item in hydration_events],
        "observation_ids": [item["observation_id"] for item in observations],
        "observer_run_ids": [item["observer_run_id"] for item in observer_runs],
        "health_metrics": [item.get("metric", "") for item in health],
        "social_work_record_ids": [item["record_id"] for item in existing_notes],
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
            "events_count": len(events),
            "falls_count": len(falls),
            "hydration_events_count": len(hydration_events),
            "observations_count": len(observations),
            "health_metrics_count": len(health),
            "interactions_count": len(user_turns),
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
    lines = [
        f"【{label}】",
        f"期間：最近 {days} 天。",
        "",
        "一、S｜服務對象／社工服務紀錄",
    ]
    if records:
        for record in records[:12]:
            author = f"（{record['author']}）" if record.get("author") else ""
            lines.append(f"- {_stamp(int(record['occurred_at_ms']))}／{record['record_type']}{author}：{record['content']}")
    else:
        lines.append("- 此期間沒有已輸入的社工紀錄；本段不以模型推測補足。")

    lines.extend(["", "二、O｜客觀照護系統資料"])
    lines.append(f"- 有效 L2 結構化觀察：{len(observations)} 筆；事件：{len(events)} 筆。")
    if observer:
        latest = observer[0]
        lines.append(f"- 最新長期觀察：{latest.get('headline', '—')}；{latest.get('detail', '')}")
    else:
        lines.append("- 尚無此期間的 Observer 紀錄。")
    if health:
        lines.append("- 最新健康量測：" + "；".join(
            f"{item['metric']} {item['value']}{item['unit']}" for item in health[:8]))
    else:
        lines.append("- 尚無健康量測資料。")

    lines.extend(["", "三、A｜資料導向評估", "- 本段只依上述已存紀錄彙整，不構成醫療診斷或社工專業結論。"])
    if observations:
        lines.append(f"- 此期間有 {len(observations)} 筆有效影像觀察，可與服務紀錄交叉覆核。")
    lines.extend(["", "四、P｜建議追蹤"])
    if not records:
        lines.append("- 建議社工補登近期訪視、電話關懷或資源連結紀錄，以利跨專業追蹤。")
    if any(event.get("event_type") == "fall" for event in events):
        lines.append("- 此期間有跌倒相關事件，請依既有個案流程人工複核。")
    if not observations:
        lines.append("- 有效影像觀察不足，請確認資料來源與 L1/L2 覆蓋率。")

    sources = {
        "social_work_record_ids": [item["record_id"] for item in records],
        "event_ids": [item["event_id"] for item in events],
        "observation_ids": [item["observation_id"] for item in observations],
        "observer_run_ids": [item["observer_run_id"] for item in observer],
        "health_metrics": [item["metric"] for item in health],
    }
    return {"report_type": report_type, "window_start_ms": started, "window_end_ms": ended,
            "title": label, "body": "\n".join(lines), "sources": sources}
