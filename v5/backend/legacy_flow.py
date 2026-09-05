"""Compatibility services for the original Longcare flow.

This module keeps the original boundaries (Main Agent, bounded context,
memory candidates and resident interaction) while using the v5 repositories
and the same local vLLM transport as L2/L3.  It deliberately stores compact
JSON, never hidden chain-of-thought or raw media.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .care_logging import CareLogger
from .domain.ids import content_hash
from .domain.model_call import ModelCall
from .domain.timeutil import now_ms
from .jsonio import JsonExtractionError, extract_json
from .local_vllm import LocalVllmClient, LocalVllmError


MAIN_PROMPT_VERSION = "main-agent.compat.v1"
INTERACTION_PROMPT_VERSION = "resident-interaction.compat.v1"
UNDERSTANDING_PROMPT_VERSION = "resident-understanding.compat.v1"


class LegacyFlow:
    def __init__(self, repos: Any, subject_id: str, client: Any = None,
                 *, use_stub: bool = False, model: str = "nemotron_omni") -> None:
        self.repos = repos
        self.subject_id = subject_id
        self.client = client if hasattr(client, "generate") else None
        self.use_stub = use_stub or self.client is None
        self.model = getattr(self.client, "model", model)
        self.provider = "stub" if self.use_stub else "local_vllm"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="main-agent")
        self._lock = threading.Lock()
        self._pending: set[str] = set()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- main agent ------------------------------------------------------

    def submit_main_agent(self, *, window: dict[str, Any], observation: dict[str, Any],
                          persisted: dict[str, Any] | None = None,
                          frames: list[bytes] | None = None,
                          audio_pcm: bytes | None = None,
                          trigger_type: str = "multimodal_window") -> bool:
        window_id = str(window.get("window_id") or "window")
        dedup = f"main_agent:{self.subject_id}:{window_id}:{trigger_type}"
        with self._lock:
            if dedup in self._pending:
                return False
            self._pending.add(dedup)

        def run() -> None:
            try:
                self.run_main_agent(
                    window=window, observation=observation, persisted=persisted,
                    frames=frames, audio_pcm=audio_pcm, trigger_type=trigger_type,
                    dedup_key=dedup,
                )
            finally:
                with self._lock:
                    self._pending.discard(dedup)

        self._executor.submit(run)
        return True

    def run_main_agent(self, *, window: dict[str, Any], observation: dict[str, Any],
                       persisted: dict[str, Any] | None = None,
                       frames: list[bytes] | None = None,
                       audio_pcm: bytes | None = None,
                       trigger_type: str = "multimodal_window",
                       dedup_key: str | None = None) -> dict[str, Any]:
        context = self._main_context(window, observation, persisted or {})
        run_id, is_new = self.repos.save_agent_run(
            self.subject_id, "main_agent", trigger_type,
            str(window.get("window_id") or ""), str(window.get("window_id") or ""),
            context, dedup_key or f"main_agent:{self.subject_id}:{now_ms()}",
            provider=self.provider, model=self.model,
        )
        if not is_new:
            rows = self.repos.list_agent_runs(limit=20, agent_name="main_agent")
            return next((r for r in rows if r.get("agent_run_id") == run_id), {"agent_run_id": run_id})

        started = time.perf_counter()
        try:
            if self.use_stub:
                result = self._stub_main(observation, window)
                call = self._audit_call("main_agent", MAIN_PROMPT_VERSION, context, result, 0, "ok")
            else:
                result, call = self._generate_json(
                    purpose="main_agent", prompt_version=MAIN_PROMPT_VERSION,
                    system=self._main_system(), prompt=self._main_prompt(context),
                    frames=frames, audio_pcm=audio_pcm, max_output_tokens=1800,
                )
            self.repos.finish_agent_run(run_id, "completed", result, latency_ms=call.latency_ms)
            return {"agent_run_id": run_id, "status": "completed", "judgment": result,
                    "model_call_id": call.call_id}
        except Exception as exc:  # noqa: BLE001 - agent is advisory and fail-closed
            latency = int((time.perf_counter() - started) * 1000)
            self.repos.finish_agent_run(run_id, "failed", {}, type(exc).__name__, latency)
            return {"agent_run_id": run_id, "status": "failed", "error_code": type(exc).__name__}

    # -- resident interaction ------------------------------------------

    def interaction(self, text: str, conversation_id: str = "default") -> dict[str, Any]:
        text = text.strip()[:2000]
        if not text:
            raise ValueError("text is required")
        context = {
            "subject_id": self.subject_id,
            "conversation_id": conversation_id,
            "conversation_history": self._compact_messages(conversation_id),
            "confirmed_memories": self._compact_memories("confirmed", 30),
            "main_agent_runs": self._compact_agent_runs(6),
            "current_user_input": text,
            "input_channel": "text",
            "emergency_response": False,
        }
        dedup = f"interaction:{conversation_id}:{now_ms()}"
        run_id, _ = self.repos.save_agent_run(
            self.subject_id, "resident_interaction", "text_turn", conversation_id,
            None, context, dedup, provider=self.provider, model=self.model,
        )
        started = time.perf_counter()
        try:
            if self.use_stub:
                reply = self._stub_interaction(text)
                call = self._audit_call("resident_interaction", INTERACTION_PROMPT_VERSION,
                                         context, reply, 0, "ok")
            else:
                reply, call = self._generate_json(
                    purpose="resident_interaction", prompt_version=INTERACTION_PROMPT_VERSION,
                    system=self._interaction_system(), prompt=self._interaction_prompt(context),
                    max_output_tokens=900,
                )
            reply = self._normalise_reply(reply, text)
            self.repos.add_interaction_message(self.subject_id, conversation_id, "user", text,
                                               "input", run_id)
            self.repos.add_interaction_message(self.subject_id, conversation_id, "assistant",
                                               reply["reply_text"], reply["intent"], run_id)
            for candidate in reply.get("memory_candidates", []):
                if isinstance(candidate, dict) and candidate.get("title") and candidate.get("content"):
                    self.repos.save_memory(
                        self.subject_id, str(candidate.get("memory_type", "preference")),
                        str(candidate["title"]), str(candidate["content"]),
                        float(candidate.get("confidence", 0.5)), run_id, True,
                    )
            self.repos.finish_agent_run(run_id, "completed", reply, latency_ms=call.latency_ms)
            CareLogger.get().info("interaction", f"Resident turn: \"{text[:60]}\" -> intent={reply.get('intent')}, reply=\"{reply.get('reply_text', '')[:60]}\"")
            return {"status": "completed", "agent_run_id": run_id, **reply}
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - started) * 1000)
            CareLogger.get().error("interaction", f"Resident turn failed: {type(exc).__name__}: {exc}")
            fallback = {"reply_text": "抱歉，我現在沒辦法好好回覆，請稍後再試。",
                        "intent": "unknown", "should_speak": True, "confidence": 0.0}
            self.repos.finish_agent_run(run_id, "failed", fallback, type(exc).__name__, latency)
            return {"status": "failed", "agent_run_id": run_id, "error_code": type(exc).__name__, **fallback}

    def understanding(self, conversation_id: str = "default") -> dict[str, Any]:
        context = {
            "subject_id": self.subject_id,
            "conversation_history": self._compact_messages(conversation_id),
            "recent_events": self.repos.list_events(limit=12),
            "confirmed_memories": self._compact_memories("confirmed", 30),
            "recent_agent_runs": self._compact_agent_runs(8),
        }
        run_id, _ = self.repos.save_agent_run(
            self.subject_id, "resident_understanding", "background_infer", conversation_id,
            None, context, f"understanding:{conversation_id}:{now_ms()}",
            provider=self.provider, model=self.model,
        )
        try:
            if self.use_stub:
                insight = {"observed_pattern": "我觀察到目前累積的互動資料仍然有限。",
                           "user_perspective": "如果我是使用者，我希望系統先保持安靜並尊重我的選擇。",
                           "preference_hypotheses": [], "state_hypotheses": [],
                           "memory_candidates": [], "should_initiate": False,
                           "suggested_message": "", "initiation_reasons": [], "confidence": 0.3}
                call = self._audit_call("resident_understanding", UNDERSTANDING_PROMPT_VERSION,
                                         context, insight, 0, "ok")
            else:
                insight, call = self._generate_json(
                    purpose="resident_understanding", prompt_version=UNDERSTANDING_PROMPT_VERSION,
                    system=self._understanding_system(), prompt=self._understanding_prompt(context),
                    max_output_tokens=1000,
                )
            insight = self._normalise_understanding(insight)
            for candidate in insight.get("memory_candidates", []):
                if isinstance(candidate, dict) and candidate.get("title") and candidate.get("content"):
                    self.repos.save_memory(self.subject_id, "preference", str(candidate["title"]),
                                           str(candidate["content"]), float(candidate.get("confidence", 0.4)),
                                           run_id, True)
            self.repos.finish_agent_run(run_id, "completed", insight, latency_ms=call.latency_ms)
            return {"status": "completed", "agent_run_id": run_id, "insight": insight}
        except Exception as exc:  # noqa: BLE001
            self.repos.finish_agent_run(run_id, "failed", {}, type(exc).__name__)
            return {"status": "failed", "agent_run_id": run_id, "error_code": type(exc).__name__}

    # -- prompts and transport -----------------------------------------

    def _generate_json(self, *, purpose: str, prompt_version: str, system: str,
                       prompt: str, frames: list[bytes] | None = None,
                       audio_pcm: bytes | None = None, max_output_tokens: int = 1000) -> tuple[dict[str, Any], ModelCall]:
        if self.client is None or not hasattr(self.client, "generate"):
            raise RuntimeError("no model client configured for legacy flow")
        provider = "local_vllm" if isinstance(self.client, LocalVllmClient) else getattr(self.client, "provider", "gemini")
        if hasattr(self.client, "text_part"):
            parts = [self.client.text_part(prompt)]
            if frames and hasattr(self.client, "frame_parts"):
                parts.extend(self.client.frame_parts(frames))
            if audio_pcm and hasattr(self.client, "audio_part"):
                parts.append(self.client.audio_part(audio_pcm))
        else:
            parts = [{"text": prompt}]
        started = time.perf_counter()
        call = ModelCall(
            provider=provider, model=getattr(self.client, "model", self.model), purpose=purpose,
            layer="l2_gemini", prompt_version=prompt_version, schema_version=f"{purpose}.v1",
            input_hash=content_hash(prompt, str(len(frames or []))),
        )
        try:
            response = self.client.generate(parts, system_instruction=system,
                                            max_output_tokens=max_output_tokens)
            call.latency_ms = response.latency_ms
            call.prompt_tokens = response.prompt_tokens
            call.output_tokens = response.output_tokens
            call.total_tokens = response.total_tokens
            call.response_text = response.text[:4000]
            try:
                raw = extract_json(response.text)
                if not isinstance(raw, dict):
                    raise ValueError("model JSON is not an object")
            except (JsonExtractionError, ValueError) as first_error:
                # Match the original one-repair rule, but never retry a
                # transport error as if it were malformed model output.
                call.attempts = 2
                repair_msg = (
                    f"只修正 JSON 格式，不改變判斷。錯誤：{first_error}\n"
                    f"原始輸出：{response.text[:2400]}\n請重新輸出 JSON。"
                )
                repair_part = self.client.text_part(repair_msg) if hasattr(self.client, "text_part") else {"text": repair_msg}
                repair = self.client.generate(
                    [repair_part],
                    system_instruction=system,
                    max_output_tokens=max_output_tokens,
                )
                call.latency_ms += repair.latency_ms
                call.output_tokens = (call.output_tokens or 0) + (repair.output_tokens or 0)
                call.total_tokens = (call.total_tokens or 0) + (repair.total_tokens or 0)
                call.response_text = repair.text[:4000]
                raw = extract_json(repair.text)
                if not isinstance(raw, dict):
                    raise ValueError("repaired JSON is not an object")
                call.status = "repaired"
            else:
                call.status = "ok"
            self.repos.save_model_call(call)
            return raw, call
        except Exception as exc:
            call.status = "failed"
            call.error_code = getattr(exc, "code", type(exc).__name__)
            call.error_message = str(exc)[:600]
            call.latency_ms = int((time.perf_counter() - started) * 1000)
            self.repos.save_model_call(call)
            raise

    def _audit_call(self, purpose: str, prompt_version: str, context: dict[str, Any],
                    result: dict[str, Any], latency_ms: int, status: str) -> ModelCall:
        call = ModelCall(
            provider=self.provider, model=self.model, purpose=purpose,
            layer="l2_gemini", prompt_version=prompt_version, schema_version=f"{purpose}.v1",
            status=status, latency_ms=latency_ms,
            input_hash=content_hash(json.dumps(context, ensure_ascii=False, default=str), purpose),
            response_text=json.dumps(result, ensure_ascii=False)[:4000],
        )
        self.repos.save_model_call(call)
        return call

    def _main_context(self, window: dict[str, Any], observation: dict[str, Any],
                      persisted: dict[str, Any]) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "window": window,
            "observation": observation,
            "events": persisted.get("events", self.repos.list_events(limit=12))[:12],
            "recognition_events": persisted.get("recognition_events", []),
            "recent_agent_runs": self._compact_agent_runs(6),
            "confirmed_memories": self._compact_memories("confirmed", 30),
            "memory_policy": "memory candidates are hypotheses and require confirmation",
            "raw_media_policy": "only attached current frames are evidence; do not infer unseen footage",
        }

    def _compact_agent_runs(self, limit: int) -> list[dict[str, Any]]:
        """Never feed a previous run's full context back into the model."""
        out = []
        for run in self.repos.list_agent_runs(limit=limit):
            output = run.get("output") if isinstance(run.get("output"), dict) else {}
            out.append({
                "agent_run_id": run.get("agent_run_id"),
                "agent_name": run.get("agent_name"),
                "trigger_type": run.get("trigger_type"),
                "status": run.get("status"),
                "created_at": run.get("created_at"),
                "summary": str(output.get("situation_summary") or output.get("reply_text") or output.get("observed_pattern") or "")[:500],
                "risk_level": output.get("risk_level"),
                "intent": output.get("intent"),
            })
        return out

    def _compact_messages(self, conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {"role": item.get("role"), "text": str(item.get("text", ""))[:600],
             "intent": item.get("intent"), "created_at": item.get("created_at")}
            for item in self.repos.interaction_messages(self.subject_id, conversation_id, limit)
        ]

    def _compact_memories(self, status: str, limit: int) -> list[dict[str, Any]]:
        return [
            {"memory_id": item.get("memory_id"), "memory_type": item.get("memory_type"),
             "title": item.get("title"), "content": str(item.get("content", ""))[:600],
             "confidence": item.get("confidence")}
            for item in self.repos.list_memories(self.subject_id, status, limit)
        ]

    @staticmethod
    def _main_system() -> str:
        return ("你是 Longcare 的 Main Agent。只輸出可稽核 JSON，不輸出隱藏推理。"
                "只把目前 evidence 支持的內容列為 observed_facts；未知要保留為 unknown。"
                "fall/hydration 只是 observation，不能自行宣稱 confirmed；action 只是建議，不能宣稱已通知或已執行。")

    @staticmethod
    def _main_prompt(context: dict[str, Any]) -> str:
        return "請依 main-agent-judgment.v1 分析有限窗口，輸出欄位 situation_summary、temporal_assessment、observed_facts、event_assessments、hypotheses、unknowns、uncertainty_reasons、risk_level、attention_level、proposed_action、decision_reasons、next_action、ask_question、caregiver_summary、evidence_frame_indexes、confidence、attention_reason、needs_further_attention、segment_record。context=" + json.dumps(context, ensure_ascii=False, default=str)

    @staticmethod
    def _interaction_system() -> str:
        return (
            "你是長者照護系統中溫暖貼心的「住民陪伴照護助理」。"
            "你的任務是以親切、自然、具備同理心且尊重的繁體中文與長輩對話，如同細心的照服員或家人一般關心他們的生活起居。\n"
            "原則：\n"
            "1. 自然對話：具體回答長輩的問題，表達真誠關懷與陪伴，絕不使用機械化、泛化的固定罐頭語句。\n"
            "2. 意圖識別（intent）：conversation (日常閒聊與分享), question (詢問問題), help (求助或需要協助), stop (要求停止發話或保持安靜), forget (要求刪除/遺忘紀錄), preference_statement (表明生活喜好或習慣), schedule_reminder (設定提醒)。\n"
            "3. 記憶萃取：長輩若在對話中表達生活偏好或習慣，萃取成 memory_candidates（requires_confirmation=true）。\n"
            "4. 安全防線：不做醫療診斷，不宣稱已完成未授權的外部實體操作；若有緊急或危險情況，溫暖安撫並說明會通知照護人員。\n"
            "5. 請只輸出合法的 JSON 物件。"
        )

    @staticmethod
    def _interaction_prompt(context: dict[str, Any]) -> str:
        history = context.get("conversation_history", [])
        history_lines = []
        for msg in history[-8:]:
            role_label = "長輩" if msg.get("role") == "user" else "照護助理"
            history_lines.append(f"{role_label}: {msg.get('text', '')}")
        history_text = "\n".join(history_lines) if history_lines else "（這是本次對話的第一句）"

        current_input = context.get("current_user_input", "")
        memories = context.get("confirmed_memories", [])
        memories_text = "、".join(f"{m.get('title')}: {m.get('content')}" for m in memories[:6]) if memories else "無特定偏好紀錄"

        return (
            f"【長輩對照護助理說】：\"{current_input}\"\n\n"
            f"【近期對話歷史】：\n{history_text}\n\n"
            f"【已知長輩偏好】：{memories_text}\n\n"
            "請針對長輩當前的話語，給予溫暖、自然、具體且貼切的回應。直接回答問題，不要回覆準備好幫忙或等待提問等敷衍文字。\n"
            "輸出 JSON 格式 (resident-interaction-reply.v1)：\n"
            "{\n"
            "  \"reply_text\": \"給長輩的溫暖自然口語回覆\",\n"
            "  \"intent\": \"conversation | question | help | stop | forget | preference_statement | schedule_reminder\",\n"
            "  \"tone\": \"warm\",\n"
            "  \"should_speak\": true,\n"
            "  \"confidence\": 0.95,\n"
            "  \"memory_candidates\": [],\n"
            "  \"reported_event_type\": null,\n"
            "  \"reported_event_summary\": null,\n"
            "  \"reminder_time\": null,\n"
            "  \"reminder_text\": null,\n"
            "  \"safety_notes\": []\n"
            "}"
        )

    @staticmethod
    def _understanding_system() -> str:
        return ("你是只做背景歸納的 Resident Understanding Agent。永遠不要直接對使用者說話。"
                "所有偏好與狀態都只是 hypothesis，memory_candidates 必須 requires_confirmation=true。只輸出 JSON。")

    @staticmethod
    def _understanding_prompt(context: dict[str, Any]) -> str:
        return "請輸出 resident-understanding-insight.v1：observed_pattern、user_perspective、preference_hypotheses、state_hypotheses、memory_candidates、should_initiate、suggested_message、initiation_reasons、confidence。context=" + json.dumps(context, ensure_ascii=False, default=str)

    # -- conservative normalisation -----------------------------------

    @staticmethod
    def _stub_main(observation: dict[str, Any], window: dict[str, Any]) -> dict[str, Any]:
        fall = observation.get("fall") or {}
        hydration = observation.get("hydration") or {}
        fall_like = bool(fall.get("posture") == "lying" and fall.get("near_floor"))
        hydration_like = bool(hydration.get("container_near_mouth") or hydration.get("drinking_motion"))
        return {"situation_summary": "目前窗口已完成保守分析。", "temporal_assessment": "依目前窗口的有限 frame 觀察。",
                "observed_facts": [str(observation.get("scene_summary") or "目前沒有額外場景描述。")],
                "event_assessments": ([{"event_type": "fall", "assessment": "possible", "confidence": fall.get("confidence", 0), "reason": "fall observation", "evidence_frame_indexes": []}] if fall_like else []),
                "hypotheses": [], "unknowns": ["沒有連續窗口以外的直接影像證據。"],
                "uncertainty_reasons": ["offline_stub"], "risk_level": "high" if fall_like else ("low" if hydration_like else "none"),
                "attention_level": "high" if fall_like else "none", "proposed_action": "observe",
                "decision_reasons": ["model output is advisory"], "next_action": "持續觀察並由 deterministic policy 判斷。",
                "ask_question": None, "caregiver_summary": "", "evidence_frame_indexes": list(range(int(window.get("frame_count", 0)))),
                "confidence": float(observation.get("confidence", 0.0) or 0.0), "attention_reason": "offline stub",
                "needs_further_attention": fall_like, "segment_record": {"summary": "有限窗口已分析。", "observed_actions": [], "not_observed_actions": [], "uncertainty": ["offline_stub"]}}

    @staticmethod
    def _stub_interaction(text: str) -> dict[str, Any]:
        lowered = text.lower().strip()
        intent = LegacyFlow._resident_intent(text)
        candidates: list[dict[str, Any]] = []

        if intent == "stop":
            reply = "好的，我先保持安靜，您有需要隨時再叫我喔。"
        elif intent == "forget":
            reply = "我已收到您的要求，會交給後端系統處理遺忘紀錄。"
        elif intent == "help":
            reply = "我在這裡！請慢慢說，需要我幫忙聯繫照服員或家人嗎？"
        elif intent == "schedule_reminder":
            reply = "沒問題，我會記下這個提醒需求。請問您希望我什麼時候提醒您呢？"
        elif intent == "preference_statement":
            reply = "好的，我已經把您的習慣與喜好記下來了，之後會特別留意！"
            candidates.append({
                "memory_type": "preference",
                "title": "住民提醒偏好" if any(k in text for k in ("提醒", "安靜")) else "住民生活偏好",
                "content": text,
                "confidence": 0.85,
                "requires_confirmation": True,
            })
        elif any(k in lowered for k in ("早", "午安", "晚安", "你好", "您好", "嗨", "哈囉")):
            reply = "您好！今天精神感覺如何？有什麼想和我聊聊或需要幫忙的嗎？"
        elif any(k in lowered for k in ("痛", "暈", "不舒服", "累", "酸", "難過")):
            reply = "聽到您身體有些不太舒服，請先坐下或躺著多休息。若感覺沒有好轉，請告訴我，我會通知照護團隊來協助您。"
        elif any(k in lowered for k in ("水", "渴", "喝水")):
            reply = "多補充水分對健康很有幫助喔！建議您喝杯溫開水，慢慢喝別嗆著了。"
        elif any(k in lowered for k in ("名字", "你是誰", "叫什麼")):
            reply = "我是您的長照陪伴小助理，平時會陪您聊聊天、留意生活起居與安全。很高興能為您服務！"
        elif any(k in lowered for k in ("天氣", "冷", "熱", "下雨", "晴天")):
            reply = "外出或在室內都要多留意溫差變化喔，天冷記得加件外套，多喝點溫水保暖！"
        elif intent == "question":
            reply = f"您剛才提到的問題我收到了。這段時間我都在身旁陪伴您，您想多聊聊這個話題嗎？"
        else:
            reply = "謝謝您和我說話，我都在這裡聽您說。您現在感覺還好嗎？今天有沒有什麼想分享的事？"

        return {
            "reply_text": reply,
            "intent": intent,
            "tone": "warm",
            "should_speak": intent != "stop",
            "confidence": 0.85,
            "memory_candidates": candidates,
            "safety_notes": [],
            "reported_event_type": None,
            "reported_event_summary": None,
            "reminder_time": None,
            "reminder_text": None,
        }

    @staticmethod
    def _normalise_reply(raw: dict[str, Any], text: str) -> dict[str, Any]:
        if isinstance(raw.get("reply"), dict):
            raw = {**raw, **raw["reply"]}
        intents = {"conversation", "question", "reminder", "confirmation", "clarification", "repeat", "stop", "forget", "memory_query", "help", "event_report", "preference_statement", "schedule_reminder", "proactive_settings", "emergency_response", "unknown"}
        intent = str(raw.get("intent", "unknown"))
        if intent not in intents:
            intent = "preference_statement" if raw.get("memory_candidates") or raw.get("reported_event_type") == "memory_candidate_recorded" else "unknown"
        explicit_preference = any(marker in text for marker in ("請記得", "我喜歡", "我偏好", "我的習慣", "不要提醒"))
        inferred = LegacyFlow._resident_intent(text)
        if inferred != "conversation":
            intent = inferred
        if explicit_preference and intent in {"unknown", "conversation"}:
            intent = "preference_statement"
        candidates: list[dict[str, Any]] = []
        for candidate in raw.get("memory_candidates", []) if isinstance(raw.get("memory_candidates", []), list) else []:
            if isinstance(candidate, dict):
                title = str(candidate.get("title") or "住民偏好")
                content = str(candidate.get("content") or "").strip()
                if content:
                    candidates.append({**candidate, "title": title, "content": content})
            elif isinstance(candidate, str) and candidate.strip():
                candidates.append({"memory_type": "preference", "title": "住民偏好",
                                   "content": candidate.strip(), "confidence": 0.7,
                                   "requires_confirmation": True})
        if explicit_preference and not candidates:
            candidates.append({"memory_type": "preference", "title": "住民提醒偏好",
                               "content": text, "confidence": 0.9,
                               "requires_confirmation": True})
        reply_text = str(raw.get("reply_text") or raw.get("response") or "").strip()
        if not reply_text:
            reply_text = LegacyFlow._fallback_reply(text, intent)
        reported_type = raw.get("reported_event_type") if intent in {"event_report", "emergency_response"} else None
        reported_summary = raw.get("reported_event_summary") if reported_type else None
        reminder_time = raw.get("reminder_time") if intent == "schedule_reminder" else None
        reminder_text = raw.get("reminder_text") if intent == "schedule_reminder" else None
        return {"reply_text": reply_text[:1200],
                "intent": intent, "tone": str(raw.get("tone", "warm"))[:30],
                "should_speak": bool(raw.get("should_speak", intent != "stop")),
                "confidence": max(0.0, min(1.0, float(raw.get("confidence", 0.85) or 0.0))),
                "memory_candidates": candidates[:8],
                "reported_event_type": reported_type, "reported_event_summary": reported_summary,
                "reminder_time": reminder_time, "reminder_text": reminder_text,
                "safety_notes": raw.get("safety_notes", []) if isinstance(raw.get("safety_notes", []), list) else []}

    @staticmethod
    def _resident_intent(text: str) -> str:
        value = text.strip().lower()
        # 停止 / 不要說 / 先不用 are imperatives: they outrank everything.
        if any(token in value for token in ("停止", "不要說", "先不用")):
            return "stop"
        if any(token in value for token in ("忘記", "刪掉", "刪除")):
            return "forget"
        # A negated reminder is a preference about reminders, not a request
        # for one. 「不要提醒我吃藥」 contains 提醒我, and reading it as
        # schedule_reminder inverted what the resident actually asked for.
        if any(token in value for token in ("不要提醒", "不用提醒", "別提醒", "不需要提醒")):
            return "preference_statement"
        if any(token in value for token in ("提醒我", "設定提醒", "定時提醒")):
            return "schedule_reminder"
        if any(token in value for token in ("救命", "幫我", "需要幫忙", "求助")):
            return "help"
        if any(token in value for token in ("請記得", "我喜歡", "我偏好", "我的習慣", "不要提醒")):
            return "preference_statement"
        # 安靜 only reaches here as an adjective. 「請記得我喜歡安靜的提醒」
        # states a preference for quiet reminders and was being filed as a
        # demand for silence; 「安靜」 on its own still means stop.
        if "安靜" in value:
            return "stop"
        if "?" in text or "？" in text or any(token in value for token in ("什麼", "為什麼", "怎麼", "哪裡", "現在在做")):
            return "question"
        return "conversation"

    @staticmethod
    def _fallback_reply(text: str, intent: str) -> str:
        if intent == "question" and any(token in text for token in ("做什麼", "在做", "現在")):
            return "我現在正在陪你聊天，也在幫你留意重要變化。你想和我聊什麼呢？"
        if intent == "help":
            return "我在這裡，請告訴我你需要什麼協助。"
        if intent == "stop":
            return "好的，我先停止說話。"
        if intent == "forget":
            return "我收到你的忘記要求，會交給後端處理。"
        if intent == "schedule_reminder":
            return "可以，我會先記下這個提醒需求，請告訴我時間。"
        if intent == "preference_statement":
            return "好的，我會把這個偏好列為待確認記憶。"
        return "我現在有針對你的內容回應；你可以繼續告訴我想聊的事。"

    @staticmethod
    def _normalise_understanding(raw: dict[str, Any]) -> dict[str, Any]:
        observed = str(raw.get("observed_pattern") or "目前資料不足以形成穩定觀察。")
        perspective = str(raw.get("user_perspective") or "目前資料不足以推測使用者偏好。")
        if not observed.startswith("我觀察到"):
            observed = "我觀察到：" + observed
        if not perspective.startswith("如果我是使用者"):
            perspective = "如果我是使用者：" + perspective
        return {"observed_pattern": observed[:1000], "user_perspective": perspective[:1000],
                "preference_hypotheses": raw.get("preference_hypotheses", []) if isinstance(raw.get("preference_hypotheses", []), list) else [],
                "state_hypotheses": raw.get("state_hypotheses", []) if isinstance(raw.get("state_hypotheses", []), list) else [],
                "memory_candidates": raw.get("memory_candidates", []) if isinstance(raw.get("memory_candidates", []), list) else [],
                "should_initiate": bool(raw.get("should_initiate", False)),
                "suggested_message": str(raw.get("suggested_message", ""))[:500],
                "initiation_reasons": raw.get("initiation_reasons", []) if isinstance(raw.get("initiation_reasons", []), list) else [],
                "confidence": max(0.0, min(1.0, float(raw.get("confidence", 0.3) or 0.0)))}
