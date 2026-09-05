from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .adapters import GmiAsrAdapter, MiniMaxTtsAdapter, VllmVisionAdapter
from .config import Settings
from .schemas import ResidentInteractionReply, ResidentUnderstandingInsight

PROACTIVE_CONFIDENCE_THRESHOLD = 0.5
DEFAULT_PROACTIVE_COOLDOWN_MINUTES = 30


def evaluate_proactive_policy(should_initiate: bool, confidence: float, *, enabled: bool,
                              cooldown_minutes: int, last_proactive_at: str | None,
                              stop_active: bool) -> dict[str, Any]:
    """Gate the interaction driver applies before any unsolicited speech.

    The understanding/motivation driver only *proposes* initiation; it never
    speaks. This pure decision function keeps that policy auditable and testable.
    """
    now = datetime.now(timezone.utc)
    if not enabled:
        return {"allowed": False, "reason": "proactive_disabled", "next_allowed_at": None}
    if should_initiate is not True:
        return {"allowed": False, "reason": "not_proposed", "next_allowed_at": None}
    if stop_active:
        return {"allowed": False, "reason": "stop_active", "next_allowed_at": None}
    if confidence < PROACTIVE_CONFIDENCE_THRESHOLD:
        return {"allowed": False, "reason": "below_threshold", "confidence": float(confidence),
                "next_allowed_at": None}
    cooldown_seconds = max(1, int(cooldown_minutes)) * 60
    last = _parse_dt(last_proactive_at) if last_proactive_at else None
    if last is not None:
        elapsed = (now - last).total_seconds()
        if elapsed < cooldown_seconds:
            return {"allowed": False, "reason": "cooldown",
                    "minutes_elapsed": int(elapsed / 60),
                    "next_allowed_at": (last + timedelta(minutes=max(1, int(cooldown_minutes)))).isoformat()}
    return {"allowed": True, "reason": "ready",
            "next_allowed_at": (now + timedelta(minutes=max(1, int(cooldown_minutes)))).isoformat()}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_REPLY_INTENTS = ("conversation", "question", "reminder", "confirmation", "clarification",
                  "repeat", "stop", "forget", "memory_query", "help", "event_report",
                  "preference_statement", "schedule_reminder", "proactive_settings", "emergency_response", "unknown")
_REPLY_TONES = ("warm", "calm", "cheerful", "serious", "empathetic", "neutral")
_MEMORY_TYPES = ("preference", "routine", "avoidance", "accessibility", "interest",
                 "communication", "important_event")


def _normalize_memory_candidates(raw: Any, *, max_items: int = 8) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in (raw if isinstance(raw, list) else [])[:max_items]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if not title or not content:
            continue
        memory_type = item.get("memory_type")
        candidates.append({
            "memory_type": memory_type if memory_type in _MEMORY_TYPES else "preference",
            "title": title[:120],
            "content": content[:600],
            "confidence": min(1.0, max(0.0, float(item.get("confidence", 0.5) or 0.0))),
            "requires_confirmation": bool(item.get("requires_confirmation", True)),
        })
    return candidates


def normalize_resident_reply(raw: Any, *, transcript: str) -> dict[str, Any]:
    """Agent-side reply normalization, so adapters only need to return raw model output."""
    raw = raw if isinstance(raw, dict) else {}
    reply_text = str(raw.get("reply_text") or "").strip()
    if not reply_text:
        reply_text = f"我聽到你說：「{transcript}」。" if transcript else "我在這裡，請慢慢說。"
    intent = raw.get("intent")
    tone = raw.get("tone")
    follow_up = raw.get("follow_up_question")
    return {
        "reply_text": reply_text[:1200],
        "intent": intent if intent in _REPLY_INTENTS else "unknown",
        "tone": tone if tone in _REPLY_TONES else "warm",
        "used_main_agent_context": bool(raw.get("used_main_agent_context", False)),
        "memory_candidates": _normalize_memory_candidates(raw.get("memory_candidates")),
        "needs_follow_up": bool(raw.get("needs_follow_up", False)),
        "follow_up_question": str(follow_up)[:300] if follow_up else None,
        "should_speak": bool(raw.get("should_speak", True)),
        "confidence": min(1.0, max(0.0, float(raw.get("confidence", 0.5) or 0.0))),
        "safety_notes": [str(x) for x in (raw.get("safety_notes") or [])][:8],
        "reported_event_type": str(raw.get("reported_event_type"))[:80] if raw.get("reported_event_type") else None,
        "reported_event_summary": str(raw.get("reported_event_summary"))[:500] if raw.get("reported_event_summary") else None,
        "reminder_time": str(raw.get("reminder_time"))[:120] if raw.get("reminder_time") else None,
        "reminder_text": str(raw.get("reminder_text"))[:600] if raw.get("reminder_text") else None,
        "proactive_enabled": raw.get("proactive_enabled") if isinstance(raw.get("proactive_enabled"), bool) else None,
        "proactive_interval_minutes": int(raw.get("proactive_interval_minutes")) if isinstance(raw.get("proactive_interval_minutes"), (int, float)) and 30 <= int(raw.get("proactive_interval_minutes")) <= 1440 else None,
        "proactive_align_to_hour": raw.get("proactive_align_to_hour") if isinstance(raw.get("proactive_align_to_hour"), bool) else None,
    }


def normalize_resident_understanding(raw: Any) -> dict[str, Any]:
    """Agent-side insight normalization with first-person phrasing and memory candidates."""
    raw = raw if isinstance(raw, dict) else {}
    confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.0) or 0.0)))
    observed = str(raw.get("observed_pattern") or "").strip()
    if not observed.startswith("我觀察到"):
        observed = f"我觀察到：{observed}" if observed else "我觀察到近期的互動與生活模式。"
    perspective = str(raw.get("user_perspective") or "").strip()
    if not perspective.startswith("如果我是使用者"):
        perspective = f"如果我是使用者：{perspective}" if perspective else "如果我是使用者，我希望被穩定地關心。"
    preferences = [str(x).strip() for x in (raw.get("preference_hypotheses") or []) if str(x).strip()][:12]
    candidates = _normalize_memory_candidates(raw.get("memory_candidates"))
    if not candidates:
        candidates = [{"memory_type": "preference", "title": hyp[:120], "content": hyp[:600],
                       "confidence": confidence, "requires_confirmation": True} for hyp in preferences[:8]]
    return {
        "observed_pattern": observed[:1000],
        "user_perspective": perspective[:1000],
        "preference_hypotheses": preferences,
        "state_hypotheses": [str(x).strip() for x in (raw.get("state_hypotheses") or []) if str(x).strip()][:12],
        "memory_candidates": candidates,
        "should_initiate": bool(raw.get("should_initiate", False)),
        "suggested_message": str(raw.get("suggested_message") or "")[:500],
        "initiation_reasons": [str(x) for x in (raw.get("initiation_reasons") or [])][:10],
        "confidence": confidence,
    }


class ResidentInteractionAgent:
    """One resident-facing agent with two controllable driver layers.

    Both drivers share identity, conversation state and memory:
      - Interaction driver: listen (independent MiniMax M3 ASR) -> read main-agent
        records via a tool -> reply -> optional TTS. Applies stop command, consent
        and cooldown before speaking.
      - Understanding/motivation driver: runs silently in the background to infer
        preferences/state from history and to propose *whether* to proactively
        reach out. It never speaks on its own; proposals must pass through the
        interaction driver (and this policy gate) to be delivered.
    """

    def __init__(self, settings: Settings, store, *, vision=None, asr=None, tts=None, inference_semaphore=None):
        self.settings = settings
        self.store = store
        self.vision = vision or VllmVisionAdapter(settings)
        self.asr = asr or GmiAsrAdapter(settings)
        self.tts = tts or MiniMaxTtsAdapter(settings)
        self.inference_semaphore = inference_semaphore

    async def _vision_call(self, method, *args, **kwargs):
        if self.inference_semaphore is None:
            return await method(*args, **kwargs)
        async with self.inference_semaphore:
            return await method(*args, **kwargs)

    # ------------------------------------------------------------------ state
    def stop_active(self, conversation_id: str = "default") -> bool:
        marker = self.store.get_state("resident_stop_requested_at")
        return _parse_dt(marker) is not None

    # -------------------------------------------------------------- interaction
    async def turn(self, *, text: str | None = None, audio_pcm: bytes | None = None,
                   conversation_id: str = "default", speak: bool = True,
                   emergency_response: bool = False) -> dict[str, Any]:
        if self.store.high_risk_active() and not emergency_response:
            return {"status": "blocked", "reply_text": "目前正在確認一個需要注意的狀況，請先回應剛才的關心。",
                    "intent": "unknown", "should_speak": False, "asr_status": "not_started",
                    "tts_configured": self.tts_configured, "tts_mode": "browser_local",
                    "error_code": "HIGH_RISK_FLOW_ACTIVE"}
        turn_id = uuid.uuid4().hex[:16]
        asr_status = "skipped"
        transcript = (text or "").strip()
        if not transcript and audio_pcm:
            result = await self.asr.transcribe(audio_pcm)
            asr_status = result.status
            asr_payload = result.payload.get("asr") if isinstance(result.payload, dict) else None
            if result.status == "healthy" and asr_payload and asr_payload.get("transcript"):
                transcript = asr_payload["transcript"]
            else:
                transcript = f"[{asr_status}] 未能將語音轉成文字，請用文字或重複一次。"

        if emergency_response and self.store.high_risk_active() and transcript and not transcript.startswith("["):
            self.store.update_high_risk(response_received_at=_now_iso(), response_text=transcript[:1000],
                                        response_channel="voice" if audio_pcm else "text", next_question_at=None)

        context = self._read_main_agent_records(
            conversation_id, current_user_input=transcript,
            input_channel="voice" if audio_pcm else "text", emergency_response=emergency_response)
        run = self.store.record_resident_run(
            driver="interaction", trigger_type="voice_turn", trigger_id=conversation_id,
            conversation_id=conversation_id, status="running", action="transcribe_reply",
            input_json={"asr_status": asr_status, "text_length": len(transcript),
                        "tool_read_main_agent_records": True},
            provider=self.settings.inference_provider, model=self.settings.inference_model,
            dedup_key=f"interaction:voice_turn:{conversation_id}:{turn_id}")

        result = await self._vision_call(self.vision.analyze_resident_interaction, context)
        if self.store.high_risk_active() and not emergency_response:
            self.store.finish_resident_run(run["id"], status="cancelled", action="cancelled_by_high_risk",
                                           error_code="HIGH_RISK_FLOW_ACTIVE", latency_ms=result.latency_ms)
            return {"status": "blocked", "reply_text": "目前正在確認一個需要注意的狀況，請先回應剛才的關心。",
                    "intent": "unknown", "should_speak": False, "asr_status": asr_status,
                    "tts_configured": self.tts_configured, "tts_mode": "browser_local",
                    "error_code": "HIGH_RISK_FLOW_ACTIVE"}
        if result.status != "healthy":
            self._record_failed_turn(run, transcript, asr_status, "抱歉，我這陣子沒辦法好好回覆，請稍後再試。",
                                     result.error_code or "INTERACTION_UNAVAILABLE", result.latency_ms)
            return {"reply_text": "抱歉，我這陣子沒辦法好好回覆，請稍後再試。", "intent": "unknown",
                    "should_speak": True, "asr_status": asr_status,
                    "tts_configured": self.tts_configured,
                    "error_code": result.error_code or "INTERACTION_UNAVAILABLE"}

        try:
            reply_payload = result.payload.get("reply") or result.payload.get("raw")
            reply = ResidentInteractionReply.model_validate(
                normalize_resident_reply(reply_payload, transcript=transcript))
        except Exception:
            self._record_failed_turn(run, transcript, asr_status, "抱歉，我沒聽清楚。",
                                     "INVALID_RESIDENT_INTERACTION_REPLY", result.latency_ms)
            return {"reply_text": "抱歉，我沒聽清楚。", "intent": "unknown", "should_speak": True,
                    "asr_status": asr_status, "tts_configured": self.tts_configured,
                    "error_code": "INVALID_RESIDENT_INTERACTION_REPLY"}

        should_stop = reply.intent == "stop" or not reply.should_speak
        should_speak = speak and (not should_stop)
        run_id = run["id"]

        self.store.add_resident_message(conversation_id=conversation_id, role="user", text=transcript,
                                        intent="asr_input", run_id=run_id, asr_status=asr_status)
        self.store.add_resident_message(conversation_id=conversation_id, role="assistant", text=reply.reply_text,
                                        intent=reply.intent, run_id=run_id)

        for candidate in reply.memory_candidates:
            self.store.upsert_resident_memory(
                memory_type=candidate.memory_type, title=candidate.title, content=candidate.content,
                confidence=candidate.confidence, requires_confirmation=True,
                source_driver="interaction", source_run_id=run_id)

        request_event = self.store.record_resident_request(
            conversation_id=conversation_id, run_id=run_id, text=transcript,
            intent=reply.intent, confidence=reply.confidence,
            extra={"reported_event_type": reply.reported_event_type,
                   "reported_event_summary": reply.reported_event_summary,
                   "reminder_time": reply.reminder_time, "reminder_text": reply.reminder_text})
        if request_event:
            self.store.record_tool_call(
                "resident_interaction", "record_user_request",
                {"intent": reply.intent, "text_length": len(transcript), "run_id": run_id},
                {"event_id": request_event["id"], "action_executed": False})

        reminder = None
        if reply.intent == "schedule_reminder" and reply.reminder_text:
            reminder = self.store.add_resident_reminder(
                conversation_id=conversation_id, message=reply.reminder_text,
                schedule_text=reply.reminder_time or "未指定時間", source_run_id=run_id)

        proactive_settings = None
        if reply.intent == "proactive_settings":
            updates: dict[str, Any] = {}
            if reply.proactive_enabled is not None:
                self.settings.resident_proactive_speech_enabled = reply.proactive_enabled
                updates["resident_proactive_speech_enabled"] = reply.proactive_enabled
            if reply.proactive_interval_minutes is not None:
                self.settings.resident_proactive_interval_seconds = reply.proactive_interval_minutes * 60
                updates["resident_proactive_interval_seconds"] = self.settings.resident_proactive_interval_seconds
            if reply.proactive_align_to_hour is not None:
                self.settings.resident_proactive_align_to_hour = reply.proactive_align_to_hour
                updates["resident_proactive_align_to_hour"] = reply.proactive_align_to_hour
            for key, value in updates.items():
                self.store.save_setting(key, value)
            if updates:
                proactive_settings = updates
                self.store.record_tool_call("resident_interaction", "update_proactive_settings", updates,
                                            {"updated": True, "action_executed": True})

        if reply.intent == "forget":
            self.store.record_tool_call("resident_interaction", "forward_forget_to_backend",
                                        {"text": transcript},
                                        {"handled_note": "backend 負責實際刪除，driver 不假裝已刪除"})
        if should_stop:
            self.store.set_state("resident_stop_requested_at", _now_iso())
        elif not emergency_response:
            self.store.set_state("resident_stop_requested_at", None)

        output = {
            "reply_text": reply.reply_text, "intent": reply.intent, "tone": reply.tone,
            "should_speak": should_speak, "used_main_agent_context": bool(reply.used_main_agent_context),
            "needs_follow_up": reply.needs_follow_up, "follow_up_question": reply.follow_up_question,
            "confidence": reply.confidence, "safety_notes": reply.safety_notes, "asr_status": asr_status,
            "tts_mode": "browser_local" if self.settings.local_tts_enabled else ("minimax_cloud" if self.tts_configured else "disabled"),
            "request_event": request_event,
            "emergency_response": emergency_response,
            "reported_event_type": reply.reported_event_type,
            "reported_event_summary": reply.reported_event_summary,
            "reminder": reminder,
            "proactive_settings": proactive_settings,
        }
        self.store.finish_resident_run(
            run["id"], status="completed", action=(reply.intent if not should_stop else "stop"),
            output_json={"reply": reply.model_dump()}, latency_ms=result.latency_ms)

        if should_speak and not self.settings.local_tts_enabled and self.tts_configured:
            tts_result = await self._synthesize(reply.reply_text)
            if isinstance(tts_result, dict) and tts_result.get("status") == "healthy":
                payload = tts_result["payload"]
                output["tts"] = {"audio_base64": payload.get("audio_base64"),
                                 "mime_type": payload.get("mime_type")}
            else:
                output["tts_error_code"] = (isinstance(tts_result, dict) and tts_result.get("error_code")) or "TTS_UNAVAILABLE"
        return {**output, "tts_configured": self.tts_configured}

    def _record_failed_turn(self, run: dict[str, Any], transcript: str, asr_status: str,
                            fallback_reply: str, error_code: str, latency_ms: int | None) -> None:
        """Fail closed: persist the exchange and close out the audit run."""
        conversation_id = run.get("conversation_id") or "default"
        self.store.add_resident_message(conversation_id=conversation_id, role="user", text=transcript,
                                        intent="asr_input", run_id=run["id"], asr_status=asr_status)
        self.store.add_resident_message(conversation_id=conversation_id, role="assistant",
                                        text=fallback_reply, intent="unknown", run_id=run["id"])
        self.store.finish_resident_run(run["id"], status="failed", action="reply_failed",
                                       error_code=error_code, latency_ms=latency_ms)

    async def _synthesize(self, text: str):
        result = await self.tts.synthesize(text)
        if result.status != "healthy":
            return result
        payload = dict(result.payload)
        audio_bytes = payload.get("audio_bytes")
        if isinstance(audio_bytes, (bytes, bytearray)):
            payload["audio_base64"] = base64.b64encode(bytes(audio_bytes)).decode("ascii")
        payload.pop("audio_bytes", None)
        payload["artifact_id"] = f"tts_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        return {"status": "healthy", "payload": payload, "latency_ms": result.latency_ms}

    @property
    def tts_configured(self) -> bool:
        return self.settings.minimax_tts_configured

    # ------------------------------------------------------ understanding/motivation
    async def background_run(self, *, conversation_id: str = "default", force: bool = False) -> dict[str, Any]:
        if not force and (self.settings.resident_understanding_interval_seconds <= 0):
            return {"status": "disabled", "reason": "interval_not_enabled"}
        run = self.store.record_resident_run(
            driver="understanding", trigger_type="background_infer", trigger_id=conversation_id,
            conversation_id=conversation_id, status="running", action="infer_understanding",
            input_json={"force": force}, provider=self.settings.inference_provider, model=self.settings.inference_model,
            dedup_key=f"understanding:background_infer:{conversation_id}:{uuid.uuid4().hex[:16]}")

        context = self._read_main_agent_records(conversation_id, including_memories=True)
        result = await self._vision_call(self.vision.analyze_resident_understanding, context)
        if result.status != "healthy":
            self.store.finish_resident_run(run["id"], status="failed", action="infer_failed",
                                           error_code=result.error_code or "UNDERSTANDING_UNAVAILABLE",
                                           latency_ms=result.latency_ms)
            return {"status": "unavailable", "error_code": result.error_code or "UNDERSTANDING_UNAVAILABLE"}

        try:
            insight_payload = result.payload.get("insight") or result.payload.get("raw")
            insight = ResidentUnderstandingInsight.model_validate(
                normalize_resident_understanding(insight_payload))
        except Exception:
            self.store.finish_resident_run(run["id"], status="failed", action="invalid_insight",
                                           error_code="INVALID_RESIDENT_UNDERSTANDING", latency_ms=result.latency_ms)
            return {"status": "unavailable", "error_code": "INVALID_RESIDENT_UNDERSTANDING"}

        policy = evaluate_proactive_policy(
            insight.should_initiate, insight.confidence, enabled=self.settings.resident_proactive_speech_enabled,
            cooldown_minutes=self.settings.resident_proactive_cooldown_minutes,
            last_proactive_at=self.store.get_state("resident_last_proactive_at"),
            stop_active=self.stop_active(conversation_id))
        saved_insight = self.store.record_understanding_insight(
            run_id=run["id"], observed_pattern=insight.observed_pattern,
            user_perspective=insight.user_perspective,
            preference_hypotheses=insight.preference_hypotheses,
            state_hypotheses=insight.state_hypotheses, should_initiate=insight.should_initiate,
            suggested_message=insight.suggested_message, initiation_reasons=insight.initiation_reasons,
            confidence=insight.confidence, policy_json=policy,
            status="proceed" if policy["allowed"] else "review")

        for candidate in insight.memory_candidates:
            self.store.upsert_resident_memory(
                memory_type=candidate.memory_type, title=candidate.title, content=candidate.content,
                confidence=candidate.confidence, requires_confirmation=candidate.requires_confirmation,
                source_driver="understanding", source_run_id=run["id"])

        self.store.finish_resident_run(
            run["id"], status="completed", action="infer_completed",
            output_json={"insight_id": saved_insight["id"], "proposed_initiate": insight.should_initiate},
            latency_ms=result.latency_ms)

        return {"status": "completed", "insight_id": saved_insight["id"],
                "proposed_initiate": insight.should_initiate, "policy": policy}

    async def deliver_proactive(self, suggested_message: str, conversation_id: str = "default") -> dict[str, Any]:
        """Caregiver-approved proactive line: still routed through the interaction driver."""
        self.store.set_state("resident_last_proactive_at", _now_iso())
        return await self.turn(text=suggested_message or "嘿，我在這裡。", conversation_id=conversation_id)

    # -------------------------------------------------------------- context tools
    def _read_main_agent_records(self, conversation_id: str, including_memories: bool = False,
                                 current_user_input: str = "", input_channel: str = "text",
                                 emergency_response: bool = False) -> dict[str, Any]:
        notes = self.store.agent_notes(limit=40)
        recent_events_list = self.store.list_events(limit=12)[0]
        memories = self.store.resident_memory(status="confirmed", limit=50) if including_memories else []
        history = self.store.resident_messages(conversation_id=conversation_id, limit=40)
        tool_input = {"main_agent_notes": len(notes), "recent_events": len(recent_events_list)}
        self.store.record_tool_call("resident_interaction", "read_main_agent_records", tool_input,
                                    {"notes": len(notes), "events": len(recent_events_list)})
        return {
            "subject_id": self.settings.subject_id, "current_user_input": current_user_input[:2000],
            "input_channel": input_channel, "emergency_response": emergency_response,
            "conversation_history": history,
            "main_agent_notes": [str(n.get("title")) + " — " + str(n.get("content", {})) for n in notes][:20],
            "recent_events": [{"event_type": e.get("event_type"), "status": e.get("status"),
                               "occurred_at": e.get("occurred_at")} for e in recent_events_list][:12],
            "confirmed_memories": memories,
            "high_risk_state": self.store.high_risk_state(),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
