import asyncio
import tempfile
from unittest.mock import patch
from pathlib import Path

import unittest

from backend.config import Settings
from backend.db import Database
from backend.store import Store
from backend.resident import ResidentInteractionAgent, evaluate_proactive_policy
from backend.adapters import AdapterResult, GmiAsrAdapter, VllmVisionAdapter
from backend import adapters as adapter_module


class _FakeAdapter:
    def __init__(self, *, reply_raw=None, insight_raw=None):
        self.reply_raw = reply_raw or {}
        self.insight_raw = insight_raw or {}

    async def analyze_resident_interaction(self, context):
        return AdapterResult("healthy", {"reply": {**self.reply_raw}}, None, 5)

    async def analyze_resident_understanding(self, context):
        return AdapterResult("healthy", {"insight": {**self.insight_raw}}, None, 5)


class _FakeAsr(_FakeAdapter):
    def __init__(self, transcript=""):
        super().__init__()
        self.transcript = transcript

    async def transcribe(self, audio_bytes, mime_type="audio/wav"):
        if not audio_bytes:
            return AdapterResult("invalid", {}, "ASR_EMPTY_AUDIO")
        if self.transcript:
            asr = {"speech_detected": True, "transcript": self.transcript,
                   "language": "zh", "confidence": 0.9, "uncertainty_reasons": [], "schema_version": "resident-asr.v1"}
            return AdapterResult("healthy", {"asr": asr}, None, 7)
        unavailable = {"speech_detected": False, "transcript": "", "language": "unknown",
                       "confidence": 0.0, "uncertainty_reasons": ["GMI MiniMax M3 did not expose the supplied audio to the model"]}
        return AdapterResult("unavailable", {"asr": unavailable}, "GMI_M3_AUDIO_NOT_ACCEPTED")


class _FakeTts(_FakeAdapter):
    async def synthesize(self, text):
        return AdapterResult("healthy", {"audio_bytes": b"RIFFfake", "mime_type": "audio/wav"}, None, 3)


class ResidentStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(database_path=str(Path(self.tmp.name) / "care.db"), media_root=str(Path(self.tmp.name) / "media"), demo_mode="replay")
        self.db = Database(settings.database_path)
        self.db.initialize()
        self.store = Store(self.db, settings)

    def tearDown(self):
        self.tmp.cleanup()

    def test_message_and_insight_round_trip(self):
        user = self.store.add_resident_message(conversation_id="default", role="user", text="hello", intent="question", asr_status="healthy")
        assistant = self.store.add_resident_message(conversation_id="default", role="assistant", text="world", intent="answer")
        msgs = self.store.resident_messages(conversation_id="default")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertTrue(user["id"])
        self.assertTrue(assistant["id"])

    def test_resident_run_records_and_finds(self):
        run = self.store.record_resident_run(driver="interaction", trigger_type="voice_turn", trigger_id="default",
                                             conversation_id="default", status="completed", action="answer",
                                             input_json={"x": 1}, output_json={"y": 2}, provider="gmi", model="M3")
        self.assertEqual(run["status"], "completed")
        runs = self.store.resident_runs(driver="interaction")
        self.assertEqual(len(runs), 1)

    def test_memory_upsert_dedup_and_resolve(self):
        m1 = self.store.upsert_resident_memory(memory_type="preference", title="morning", content="wants water in morning", confidence=0.8, requires_confirmation=True)
        m2 = self.store.upsert_resident_memory(memory_type="preference", title="morning", content="wants water in morning", confidence=0.9, requires_confirmation=False)
        self.assertEqual(m1["id"], m2["id"])
        self.assertEqual(m1["status"], "pending")
        confirmed = self.store.resolve_resident_memory(m1["id"], "confirm")
        self.assertEqual(confirmed["status"], "confirmed")
        invalidated = self.store.resolve_resident_memory(m1["id"], "invalidate")
        self.assertEqual(invalidated["status"], "invalidated")

    def test_understanding_insight_store_echoes_status(self):
        stored = self.store.record_understanding_insight(run_id="r1", observed_pattern="x", user_perspective="y",
                                                         should_initiate=True, suggested_message="s", confidence=0.9, status="proceed")
        self.assertEqual(stored["status"], "proceed")

    def test_high_risk_state_round_trip(self):
        state = self.store.begin_high_risk(stream_id="s1", source_window_id="o1", event_type="fall",
                                           event_label="跌倒", confidence=0.9, reason="near floor",
                                           question="阿嬤還好嗎？是否跌倒？", started_at="2026-01-01T00:00:00+00:00",
                                           response_deadline_at="2026-01-01T00:01:00+00:00", next_question_at="2026-01-01T00:00:20+00:00")
        self.assertTrue(self.store.high_risk_active())
        self.assertEqual(state["status"], "awaiting_response")
        updated = self.store.update_high_risk(response_received_at="2026-01-01T00:00:10+00:00", response_text="我沒事")
        self.assertEqual(updated["response_text"], "我沒事")
        finished = self.store.finish_high_risk(status="resolved", reason="test")
        self.assertFalse(self.store.high_risk_active())
        self.assertEqual(finished["resolution_reason"], "test")

    def test_resident_reminder_accepts_hhmm(self):
        reminder = self.store.add_resident_reminder(conversation_id="default", message="喝水",
                                                    schedule_text="23:59", source_run_id="run-reminder")
        self.assertEqual(reminder["status"], "pending")
        self.assertIsNotNone(reminder["next_trigger_at"])
        self.assertEqual(len(self.store.resident_reminders(status="pending")), 1)

    def test_explicit_resident_request_is_a_recognition_event(self):
        request = self.store.record_resident_request(conversation_id="default", run_id="run-1",
                                                     text="請提醒我下午喝水", intent="reminder", confidence=0.88)
        self.assertEqual(request["event_type"], "user_request")
        self.assertEqual(request["domain"], "resident_interaction")
        self.assertFalse(request["attributes_json"]["action_executed"])
        events, _ = self.store.list_events(event_type="user_request")
        self.assertEqual(len(events), 1)
        self.assertIsNone(self.store.record_resident_request(conversation_id="default", run_id="run-2",
                                                              text="你好", intent="conversation", confidence=0.9))

    def test_m3_asr_route_stays_independent_from_local_flow(self):
        self.store.settings.flow_model_provider = "local_vlm"
        self.store.settings.minimax_base_url = "https://gmi.example"
        self.store.settings.minimax_api_key = "test-key"
        self.store.settings.minimax_model = "MiniMaxAI/MiniMax-M3"
        adapter = GmiAsrAdapter(self.store.settings)
        response = {"choices": [{"message": {"content": '{"speech_detected":true,"transcript":"你好","language":"zh","confidence":0.9,"uncertainty_reasons":[],"schema_version":"resident-asr.v1"}'}}]}
        with patch("backend.adapters._http_json", return_value=(200, response)) as request:
            result = asyncio.run(adapter.transcribe(b"RIFFfake", "audio/wav"))
        self.assertEqual(result.status, "healthy")
        self.assertEqual(request.call_args.args[1], "https://gmi.example/v1/chat/completions")
        self.assertEqual(request.call_args.kwargs["body"]["model"], "MiniMaxAI/MiniMax-M3")

    def test_resident_adapter_replaces_generic_waiting_reply(self):
        settings = Settings(database_path=str(Path(self.tmp.name) / "adapter.db"), media_root=str(Path(self.tmp.name) / "media"),
                             flow_model_provider="local_vlm", vllm_base_url="http://vllm.test/v1", vllm_model="nemotron_omni")
        response = {"choices": [{"message": {"content": '{"reply_text":"我正在等待您的下一句","intent":"stop","tone":"neutral","used_main_agent_context":false,"memory_candidates":[],"needs_follow_up":false,"follow_up_question":null,"should_speak":true,"confidence":0.9,"safety_notes":[],"reported_event_type":null,"reported_event_summary":null,"reminder_time":null,"reminder_text":null,"proactive_enabled":null,"proactive_interval_minutes":null,"proactive_align_to_hour":null,"schema_version":"resident-interaction-reply.v1"}'}}]}
        with patch.object(adapter_module, "_http_json", return_value=(200, response)):
            result = asyncio.run(VllmVisionAdapter(settings).analyze_resident_interaction({"current_user_input": "你現在在做什麼？"}))
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.payload["reply"]["intent"], "question")
        self.assertIn("陪你聊天", result.payload["reply"]["reply_text"])


def _make_agent(store, reply_raw=None, insight_raw=None, transcript=""):
    settings = store.settings
    vision = _FakeAdapter(reply_raw=reply_raw or {}, insight_raw=insight_raw or {})
    return ResidentInteractionAgent(settings, store,
                                    vision=vision, asr=_FakeAsr(transcript=transcript),
                                    tts=_FakeTts())


class ResidentTurnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(database_path=str(Path(self.tmp.name) / "care.db"), media_root=str(Path(self.tmp.name) / "media"), demo_mode="replay",
                            minimax_tts_base_url="", minimax_tts_api_key="")
        self.db = Database(settings.database_path)
        self.db.initialize()
        self.store = Store(self.db, settings)

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_turn_persists_and_no_tts_when_unconfigured(self):
        agent = _make_agent(self.store)
        result = asyncio.run(agent.turn(text="hello there", conversation_id="default", speak=True))
        self.assertIn("hello", result["reply_text"])
        self.assertFalse(result["tts_configured"])
        self.assertEqual(result["tts_mode"], "browser_local")
        msgs = self.store.resident_messages(conversation_id="default")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])

    def test_user_request_is_returned_and_saved_in_timeline(self):
        agent = _make_agent(self.store, reply_raw={"reply_text": "好的，下午提醒你。", "intent": "reminder", "confidence": 0.9})
        result = asyncio.run(agent.turn(text="下午提醒我喝水", conversation_id="default", speak=False))
        self.assertEqual(result["request_event"]["event_type"], "user_request")
        events, _ = self.store.list_events(event_type="user_request")
        self.assertEqual(events[0]["attributes_json"]["intent"], "reminder")

    def test_audio_turn_fail_closed_when_asr_unavailable(self):
        agent = _make_agent(self.store, transcript="")
        result = asyncio.run(agent.turn(audio_pcm=b"fakepcm", conversation_id="default"))
        self.assertEqual(result["asr_status"], "unavailable")
        msgs = self.store.resident_messages(conversation_id="default")
        self.assertEqual(msgs[-1]["role"], "assistant")

    def test_stop_intent_records_state_and_blocks_speech(self):
        agent = _make_agent(self.store, reply_raw={"reply_text": "ok stopping", "intent": "stop", "should_speak": False})
        result = asyncio.run(agent.turn(text="bye", conversation_id="default"))
        self.assertFalse(result["should_speak"])
        self.assertTrue(agent.stop_active())

    def test_forget_intents_forward_to_backend(self):
        agent = _make_agent(self.store, reply_raw={"reply_text": "forwarded", "intent": "forget"})
        asyncio.run(agent.turn(text="forget yesterday", conversation_id="default"))
        names = [t["tool_name"] for t in self.store.tool_calls(limit=50)]
        self.assertIn("forward_forget_to_backend", names)


class ResidentUnderstandingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(database_path=str(Path(self.tmp.name) / "care.db"), media_root=str(Path(self.tmp.name) / "media"), demo_mode="replay",
                            minimax_tts_base_url="", minimax_tts_api_key="",
                            resident_understanding_interval_seconds=300, resident_proactive_speech_enabled=True)
        self.settings = settings
        self.db = Database(settings.database_path)
        self.db.initialize()
        self.store = Store(self.db, settings)

    def tearDown(self):
        self.tmp.cleanup()

    def test_background_run_disabled_when_interval_zero(self):
        self.settings.resident_understanding_interval_seconds = 0
        agent = _make_agent(self.store)
        result = asyncio.run(agent.background_run(force=False))
        self.assertEqual(result["status"], "disabled")

    def test_forced_background_persists_insight_and_memory(self):
        insight_raw = {"observed_pattern": "afternoon", "user_perspective": "maybe needs a nudge",
                       "preference_hypotheses": ["prefers afternoon rest"], "should_initiate": True,
                       "suggested_message": "want a movement reminder?", "confidence": 0.9}
        agent = _make_agent(self.store, insight_raw=insight_raw)
        result = asyncio.run(agent.background_run(force=True))
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["policy"]["allowed"])
        insights = self.store.understanding_insights()
        self.assertEqual(len(insights), 1)
        self.assertTrue(insights[0]["observed_pattern"].startswith("我觀察到"))
        self.assertTrue(insights[0]["user_perspective"].startswith("如果我是使用者"))
        memories = self.store.resident_memory(status="pending")
        self.assertEqual(len(memories), 1)

    def test_proactive_disabled_by_policy_flag(self):
        policy = evaluate_proactive_policy(True, 0.9, enabled=False, cooldown_minutes=30, last_proactive_at=None, stop_active=False)
        self.assertFalse(policy["allowed"])
        self.assertEqual(policy["reason"], "proactive_disabled")


if __name__ == "__main__":
    unittest.main()
