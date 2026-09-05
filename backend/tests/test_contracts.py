import tempfile
import asyncio
import json
import wave
from io import BytesIO
import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.config import Settings
from backend.agent import MainAgentPolicy, evaluate_change_gate
from backend.change_gate import detect_frame_change, observation_override_reasons
import backend.adapters as adapter_module
from backend.adapters import VllmVisionAdapter
from backend.db import Database
from backend.replay import ReplayManager
from backend.media_stream import VirtualCameraBridge
from backend.schemas import MainAgentJudgment, VisionObservation
from backend.state_tracker import initial_state, update_state
from backend.store import Store


class CareContractsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(database_path=str(Path(self.tmp.name) / "care.db"), media_root=str(Path(self.tmp.name) / "media"), demo_mode="replay")
        self.db = Database(settings.database_path)
        self.db.initialize()
        self.store = Store(self.db, settings)

    def tearDown(self):
        self.tmp.cleanup()

    def test_motionless_window_is_still_observed_while_a_fall_is_open(self):
        """A fall candidate must keep receiving windows after motion stops.

        The gate sees no pixel change once the person is on the floor and
        still; if that suppressed the observation the fall state machine would
        never reach the second supporting observation it needs to confirm.
        """
        reasons = observation_override_reasons(
            last_observation_mono=100.0, now_mono=105.0, heartbeat_seconds=15.0,
            fall_event_open=True, hydration_session_open=False)
        self.assertIn("fall_event_open", reasons)

    def test_baseline_heartbeat_fires_when_nothing_changes(self):
        reasons = observation_override_reasons(
            last_observation_mono=100.0, now_mono=115.0, heartbeat_seconds=15.0,
            fall_event_open=False, hydration_session_open=False)
        self.assertEqual(reasons, ["baseline_heartbeat"])

    def test_quiet_window_inside_the_heartbeat_is_not_forced(self):
        reasons = observation_override_reasons(
            last_observation_mono=100.0, now_mono=104.0, heartbeat_seconds=15.0,
            fall_event_open=False, hydration_session_open=False)
        self.assertEqual(reasons, [])

    def test_first_window_is_always_observed(self):
        reasons = observation_override_reasons(
            last_observation_mono=None, now_mono=0.0, heartbeat_seconds=15.0,
            fall_event_open=False, hydration_session_open=False)
        self.assertEqual(reasons, ["baseline_heartbeat"])

    def test_heartbeat_can_be_disabled_without_dropping_open_events(self):
        reasons = observation_override_reasons(
            last_observation_mono=None, now_mono=999.0, heartbeat_seconds=0.0,
            fall_event_open=True, hydration_session_open=False)
        self.assertEqual(reasons, ["fall_event_open"])

    def test_vision_schema_rejects_invalid_model_output(self):
        with self.assertRaises(ValidationError):
            VisionObservation.model_validate({"observed_at_offset_ms": 1, "person_visible": True, "confidence": 1.2})
        with self.assertRaises(ValidationError):
            VisionObservation.model_validate({"observed_at_offset_ms": 1, "person_visible": True, "confidence": .8, "unexpected": True})

    def test_hydration_confirmed_session_is_counted_once(self):
        sequence = ReplayManager.sequence("hydration-positive")
        for observation in sequence:
            self.store.process_observation(observation, "run_test", "replay")
        for observation in sequence:
            self.store.process_observation(observation, "run_test", "replay")
        summary = self.store.hydration_summary("1970-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00")
        self.assertEqual(summary["confirmed_sessions"], 1)
        events, total = self.store.list_events(event_type="hydration")
        self.assertEqual(total, 1)
        self.assertEqual(events[0]["status"], "resolved")

    def test_fall_state_machine_requires_cross_frame_support(self):
        for observation in ReplayManager.sequence("fall-negative"):
            self.store.process_observation(observation, "negative_run", "replay")
        negative, _ = self.store.list_events(event_type="fall")
        self.assertFalse(any(item["status"] == "confirmed" for item in negative))
        for observation in ReplayManager.sequence("fall-positive"):
            self.store.process_observation(observation, "positive_run", "replay")
        events, _ = self.store.list_events(event_type="fall")
        confirmed = [item for item in events if item["status"] == "confirmed"]
        self.assertEqual(len(confirmed), 1)

    def test_action_idempotency_and_observer_rerun(self):
        for observation in ReplayManager.sequence("fall-positive"):
            self.store.process_observation(observation, "action_run", "replay")
        event, _ = self.store.list_events(event_type="fall")
        action1 = self.store.create_action(event[0]["id"], "dashboard_alert", {"severity": "acute"})
        action2 = self.store.create_action(event[0]["id"], "dashboard_alert", {"severity": "acute"})
        self.assertEqual(action1["id"], action2["id"])
        self.store.seed_history(10)
        first = self.store.observer_run()
        second = self.store.observer_run()
        self.assertEqual(len(first["summaries"]), 31)
        self.assertEqual(len(second["summaries"]), 31)
        findings, _ = self.store.db.fetch_all("SELECT * FROM observer_findings"), 0
        self.assertLessEqual(len(findings), 1)

    def test_frigate_noteworthy_gate_persists_compact_snippet_once(self):
        payload = {"frigate_event_id": "frigate-42", "camera_id": "living", "update_type": "start", "label": "fall", "zones": ["living"], "received_at": "2026-09-04T09:00:00+00:00"}
        first = self.store.record_frigate_event(**payload)
        second = self.store.record_frigate_event(**payload)
        self.assertTrue(first["noteworthy"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.frigate_logs()), 1)
        self.assertEqual(len(self.store.logs()), 1)
        ignored = self.store.record_frigate_event(frigate_event_id="frigate-43", camera_id="living", update_type="start", label="person", zones=[], received_at=payload["received_at"])
        self.assertFalse(ignored["noteworthy"])

    def test_virtual_camera_stream_tracks_chunks_without_saving_raw_media(self):
        bridge = VirtualCameraBridge(self.store.settings, self.store)

        async def exercise():
            session = await bridge.open("browser-camera", "video+audio/webm")
            await bridge.receive(session, b"webm-header")
            await bridge.receive(session, b"webm-cluster")
            return await bridge.close(session)

        result = asyncio.run(exercise())
        self.assertEqual(result["chunks_received"], 2)
        self.assertEqual(result["bytes_received"], len(b"webm-headerwebm-cluster"))
        self.assertEqual(self.store.db.fetch_one("SELECT COUNT(*) AS n FROM virtual_camera_streams")["n"], 1)
        columns = {row["name"] for row in self.store.db.fetch_all("PRAGMA table_info(virtual_camera_streams)")}
        self.assertNotIn("path", columns)

    def test_vllm_observation_parser_accepts_reasoning_model_json(self):
        raw = VllmVisionAdapter._extract_json("brief preface\n```json\n{\"observed_at_offset_ms\":0,\"person_visible\":false,\"posture\":\"unknown\",\"vertical_transition\":\"unknown\",\"near_floor\":false,\"drink_container\":\"none\",\"container_near_mouth\":false,\"drinking_motion\":false,\"confidence\":0.1,\"supporting_frame_indexes\":[],\"uncertainty_reasons\":[\"no person\"]}\n```\n")
        observation = VisionObservation.model_validate(raw)
        self.assertFalse(observation.person_visible)
        self.assertEqual(observation.posture, "unknown")

    def test_omni_change_gate_can_disable_thinking_per_request(self):
        captured = {}
        original = adapter_module._http_json

        def fake_http(method, url, **kwargs):
            captured.update(kwargs)
            return 200, {"choices": [{"message": {"content": json.dumps({
                "changed": True, "change_score": .7, "change_summary": "偵測到畫面變化。",
                "change_reasons": ["visual_change"], "confidence": .9,
            }, ensure_ascii=False)}}]}

        adapter_module._http_json = fake_http
        try:
            result = asyncio.run(VllmVisionAdapter(self.store.settings).analyze_change_gate((b"frame-a", b"frame-b"), {"window_id": "g1"}))
        finally:
            adapter_module._http_json = original
        self.assertEqual(result.status, "healthy")
        self.assertFalse(captured["body"]["chat_template_kwargs"]["enable_thinking"])

    def test_visual_description_prompt_is_action_only(self):
        captured = {}
        original = adapter_module._http_json

        def fake_http(method, url, **kwargs):
            captured.update(kwargs)
            return 200, {"choices": [{"message": {"content": json.dumps({
                "description": "人物從坐姿站起。", "observed_facts": ["人物站起"], "visible_objects": [],
                "person_actions": ["從坐姿站起"], "changes": ["姿態由坐姿變為站立"], "warnings": [], "unknowns": [],
                "confidence": .88, "warning_level": "none", "schema_version": "visual-description.v1",
            }, ensure_ascii=False)}}]}

        adapter_module._http_json = fake_http
        try:
            result = asyncio.run(VllmVisionAdapter(self.store.settings).analyze_visual_description(
                (b"frame-a", b"frame-b"), {"window_id": "d1"}, scene_context={"location": "test"}))
        finally:
            adapter_module._http_json = original
        self.assertEqual(result.status, "healthy")
        prompt = captured["body"]["messages"][0]["content"][0]["text"]
        self.assertIn("只描述這段時間人物或物品的動作與狀態變化", prompt)
        self.assertIn("不要重複場景 bootstrap", prompt)

    def test_observation_evidence_keeps_window_offsets(self):
        observation = VisionObservation(observed_at_offset_ms=5000, person_visible=False, posture="unknown", vertical_transition="unknown", near_floor=False,
                                        drink_container="none", container_near_mouth=False, drinking_motion=False, confidence=0.2)
        result = self.store.process_observation(observation, "window_run", "vllm", {"window_id": "window_run:w1", "start_offset_ms": 0, "end_offset_ms": 5000, "frame_count": 10, "sample_fps": 2.0, "window_seconds": 5.0})
        evidence = self.store.db.fetch_one("SELECT source_offset_start_ms,source_offset_end_ms,metadata_json FROM evidence WHERE id=?", (result["evidence_id"],))
        self.assertEqual((evidence["source_offset_start_ms"], evidence["source_offset_end_ms"]), (0, 5000))
        self.assertEqual(json.loads(evidence["metadata_json"])["frame_count"], 10)

    def test_pcm_audio_is_wrapped_as_transient_wav_for_vllm(self):
        wav_bytes = VllmVisionAdapter._pcm_to_wav(b"\x00\x00" * 16000)
        with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
            self.assertEqual((wav_file.getnchannels(), wav_file.getsampwidth(), wav_file.getframerate(), wav_file.getnframes()), (1, 2, 16000, 16000))

    def test_exception_event_candidates_use_existing_event_contract_shape(self):
        observation = VisionObservation(observed_at_offset_ms=5000, person_visible=True, posture="sitting", vertical_transition="none", confidence=.8,
                                        drink_container="none", audio_present=True, audio_events=["door_knock"], speaker_emotion="neutral",
                                        event_candidates=[{"event_type": "door_knock", "domain": "sound", "label": "door knock", "state": "started", "confidence": .82, "evidence_frame_indexes": [0, 2, 4], "attributes": {"source": "audio"}, "uncertainty_reasons": []}])
        result = self.store.process_observation(observation, "candidate_run", "vllm", {"window_id": "candidate_run:w1", "start_offset_ms": 0, "end_offset_ms": 5000, "frame_count": 10})
        self.assertEqual(len(result["recognition_events"]), 1)
        self.assertEqual(result["recognition_events"][0]["event_type"], "door_knock")
        events, total = self.store.list_events()
        self.assertEqual(total, 1)
        self.assertEqual(events[0]["attributes_json"]["window"]["frame_count"], 10)

    def test_main_agent_low_confidence_fails_closed(self):
        observation = VisionObservation(observed_at_offset_ms=5000, person_visible=False, posture="unknown",
                                        vertical_transition="unknown", confidence=.35, audio_present=False)
        judgment = MainAgentJudgment(situation_summary="無法從窗口確認值得注意事件。", situation_phase="unclear",
                                     temporal_assessment="影像證據不足，沒有可確認的跨 frame 變化。", risk_level="unknown",
                                     attention_level="high", proposed_action="dashboard_alert", next_action="保持安靜並等待更多資料。",
                                     confidence=.30, unknowns=["目前場景不可觀測"], uncertainty_reasons=["low confidence"])
        result = MainAgentPolicy(self.store.settings).evaluate(judgment, observation, {"events": [], "recognition_events": []}, {"window_id": "w1", "frame_count": 10})
        self.assertEqual(result["final_action"], "silent")
        self.assertEqual(result["decision"], "insufficient_data")
        self.assertFalse(result["action_allowed"])

    def test_main_agent_normal_clear_observation_stays_silent(self):
        observation = VisionObservation(observed_at_offset_ms=5000, person_visible=True, posture="sitting",
                                        vertical_transition="none", confidence=.92, supporting_frame_indexes=[0, 4, 9])
        judgment = MainAgentJudgment(situation_summary="人物穩定坐著，沒有值得注意的事件。", situation_phase="no_change",
                                     temporal_assessment="十張 frame 都是穩定坐姿，沒有明顯下墜或異常聲音。", risk_level="normal",
                                     attention_level="none", proposed_action="silent", next_action="保持安靜並持續觀察。",
                                     confidence=.93, observed_facts=["人物可見", "姿勢穩定"], evidence_frame_indexes=[0, 4, 9])
        result = MainAgentPolicy(self.store.settings).evaluate(judgment, observation, {"events": [], "recognition_events": []}, {"window_id": "w-normal", "frame_count": 10})
        self.assertEqual(result["final_action"], "silent")
        self.assertLess(result["attention_score"], 55)

    def test_change_gate_triggers_when_person_appears(self):
        previous = VisionObservation(observed_at_offset_ms=0, person_visible=False, posture="unknown", confidence=.8)
        current = VisionObservation(observed_at_offset_ms=5000, person_visible=True, posture="sitting", confidence=.8)
        result = evaluate_change_gate(previous, current, {"events": [], "recognition_events": []})
        self.assertTrue(result["trigger"])
        self.assertIn("person_appeared", result["reasons"])

    def test_change_gate_triggers_once_for_new_memorable_event(self):
        previous = VisionObservation(observed_at_offset_ms=0, person_visible=True, posture="sitting", confidence=.8,
                                     audio_present=True, audio_events=["background_music"])
        current = VisionObservation(observed_at_offset_ms=5000, person_visible=True, posture="sitting", confidence=.8,
                                    audio_present=True, audio_events=["door_knock"], event_candidates=[{"event_type": "door_knock", "domain": "sound", "label": "door knock", "state": "started", "confidence": .82}])
        first = evaluate_change_gate(previous, current, {"events": [], "recognition_events": []})
        second = evaluate_change_gate(current, current, {"events": [], "recognition_events": []}, first["event_keys"])
        self.assertTrue(first["trigger"])
        self.assertIn("new_audio_event:door_knock", first["reasons"])
        self.assertFalse(second["trigger"])

    def test_main_agent_critical_recognition_overrides_model_action(self):
        observation = VisionObservation(observed_at_offset_ms=5000, person_visible=False, posture="unknown",
                                        vertical_transition="unknown", confidence=.82, audio_present=True,
                                        audio_events=["alarm_sound"], audio_confidence=.88)
        judgment = MainAgentJudgment(situation_summary="窗口內疑似有警報聲。", situation_phase="emerging",
                                     temporal_assessment="聲音事件出現在目前窗口，持續時間仍有限。", risk_level="watch",
                                     attention_level="medium", proposed_action="observe", next_action="需要立即確認警報來源。",
                                     confidence=.84, observed_facts=["偵測到警報聲"], evidence_frame_indexes=[])
        persisted = {"events": [], "recognition_events": [{"id": "rec1", "event_type": "alarm_sound", "confidence": .91}]}
        result = MainAgentPolicy(self.store.settings).evaluate(judgment, observation, persisted, {"window_id": "w2", "frame_count": 10})
        self.assertEqual(result["final_action"], "dashboard_alert")
        self.assertEqual(result["risk_level"], "urgent")
        self.assertTrue(result["gates"]["critical_override"])

    def test_main_agent_run_is_idempotent_and_persisted(self):
        context = {"window": {"window_id": "w3"}, "observation": {"confidence": .8}}
        first, created = self.store.start_agent_run(agent_name="main_agent", trigger_type="multimodal_window",
                                                    trigger_id="w3", window_id="w3", input_context=context, dedup_key="dedup-w3")
        second, created_again = self.store.start_agent_run(agent_name="main_agent", trigger_type="multimodal_window",
                                                          trigger_id="w3", window_id="w3", input_context=context, dedup_key="dedup-w3")
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], second["id"])
        saved = self.store.finish_agent_run(first["id"], status="completed",
                                            judgment={"situation_summary": "測試", "confidence": .8},
                                            policy={"final_action": "observe", "attention_level": "medium", "risk_level": "watch"},
                                            model_call_id=None, latency_ms=123)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["policy_json"]["final_action"], "observe")
        trace = self.store.add_agent_run_event(first["id"], stage="policy_evaluated", event_type="agent.policy.evaluated", message="測試 policy", payload={"score": 61})
        self.assertEqual(trace["payload_json"]["score"], 61)
        self.assertEqual(self.store.agent_run_events()[0]["agent_run_id"], first["id"])
        self.assertEqual(len(self.store.agent_runs()), 1)

    def test_main_agent_adapter_sends_multimodal_schema_and_parses_judgment(self):
        judgment = {
            "situation_summary": "人物在畫面中央保持坐姿，沒有足夠證據支持危險事件。",
            "situation_phase": "no_change",
            "temporal_assessment": "十張 frame 的姿勢沒有明顯向下轉換。",
            "observed_facts": ["人物可見", "姿勢為坐姿"],
            "event_assessments": [{"event_type": "fall", "assessment": "not_supported", "confidence": .88, "reason": "沒有跨 frame 倒地證據", "evidence_frame_indexes": [0, 4, 9]}],
            "hypotheses": [], "unknowns": ["畫面外區域不可觀測"], "uncertainty_reasons": [],
            "risk_level": "normal", "attention_level": "none", "proposed_action": "silent",
            "decision_reasons": ["沒有值得升級的事件"], "next_action": "保持安靜並持續觀察。",
            "ask_question": None, "caregiver_summary": None, "evidence_frame_indexes": [0, 4, 9],
            "confidence": .88, "requires_human_review": False, "schema_version": "main-agent-judgment.v1",
        }
        captured = {}
        original = adapter_module._http_json

        def fake_http(method, url, **kwargs):
            captured.update(kwargs)
            return 200, {"choices": [{"message": {"content": json.dumps(judgment, ensure_ascii=False)}}]}

        adapter_module._http_json = fake_http
        try:
            result = asyncio.run(VllmVisionAdapter(self.store.settings).analyze_main_agent((b"fake-image",), {"window": {"window_id": "w4"}, "observation": {}}, audio_pcm=b"\x00\x00" * 16000))
        finally:
            adapter_module._http_json = original
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.payload["judgment"]["situation_phase"], "no_change")
        self.assertEqual(captured["body"]["response_format"]["json_schema"]["name"], "main_agent_judgment")
        content = captured["body"]["messages"][0]["content"]
        self.assertTrue(any(item.get("type") == "audio_url" for item in content))
        self.assertFalse(list(Path(self.store.settings.media_root).glob("vllm-audio-*.wav")))

    def test_speech_transcript_is_saved_with_ttl_when_omni_detects_speech(self):
        observation = VisionObservation(observed_at_offset_ms=5000, person_visible=True, posture="sitting",
                                        vertical_transition="none", confidence=.8, audio_present=True,
                                        audio_events=["speech_activity"], speech_detected=True,
                                        speech_transcript="我有點不舒服", transcript_confidence=.82)
        result = self.store.process_observation(observation, "speech-run", "vllm", {"window_id": "speech-run:w1", "start_offset_ms": 0, "end_offset_ms": 5000, "frame_count": 10})
        self.assertEqual(result["transcript"]["text"], "我有點不舒服")
        saved = self.db.fetch_one("SELECT text,language,confidence,retention_until FROM transcripts WHERE id=?", (result["transcript"]["id"],))
        self.assertEqual((saved["text"], saved["language"]), ("我有點不舒服", "zh-TW"))
        self.assertAlmostEqual(saved["confidence"], .82)
        self.assertTrue(saved["retention_until"])

    def test_temporal_tracker_confirms_stand_and_sit_with_estimated_offsets(self):
        def observation(offset, posture):
            return VisionObservation(observed_at_offset_ms=offset, person_visible=True, posture=posture,
                                     vertical_transition="none", confidence=.9, supporting_frame_indexes=[0, 4, 9])

        state = initial_state()
        first = update_state(state, observation(5000, "sitting"), {"start_offset_ms": 0, "end_offset_ms": 5000})
        second = update_state(first["state"], observation(10000, "standing"), {"start_offset_ms": 5000, "end_offset_ms": 10000})
        third = update_state(second["state"], observation(15000, "standing"), {"start_offset_ms": 10000, "end_offset_ms": 15000})
        self.assertIsNone(first["transition"])
        self.assertIsNone(second["transition"])
        self.assertEqual(third["transition"]["event_type"], "person_stood_up")
        self.assertEqual(third["transition"]["occurred_offset_ms"], 7500)

        fourth = update_state(third["state"], observation(20000, "sitting"), {"start_offset_ms": 15000, "end_offset_ms": 20000})
        fifth = update_state(fourth["state"], observation(25000, "sitting"), {"start_offset_ms": 20000, "end_offset_ms": 25000})
        self.assertEqual(fifth["transition"]["event_type"], "person_sat_down")
        self.assertEqual(fifth["transition"]["occurred_offset_ms"], 17500)

    def test_temporal_tracker_ignores_out_of_order_windows(self):
        state = initial_state()
        state = update_state(state, VisionObservation(observed_at_offset_ms=10000, person_visible=True, posture="standing", confidence=.9))["state"]
        result = update_state(state, VisionObservation(observed_at_offset_ms=5000, person_visible=True, posture="sitting", confidence=.9))
        self.assertTrue(result["ignored_out_of_order"])
        self.assertEqual(result["state"]["stable_posture"], "standing")

    def test_store_persists_posture_transition_as_recognition_event(self):
        def observation(offset, posture):
            return VisionObservation(observed_at_offset_ms=offset, person_visible=True, posture=posture,
                                     vertical_transition="none", confidence=.9, supporting_frame_indexes=[0, 4, 9])

        for item in (observation(5000, "sitting"), observation(10000, "standing"), observation(15000, "standing")):
            self.store.process_observation(item, "posture_run", "vllm", {"window_id": f"posture_run:w{item.observed_at_offset_ms}",
                                                                            "start_offset_ms": max(0, item.observed_at_offset_ms - 5000),
                                                                            "end_offset_ms": item.observed_at_offset_ms, "frame_count": 10})
        events, _ = self.store.list_events()
        transition = next(item for item in events if item["event_type"] == "person_stood_up")
        self.assertEqual(transition["status"], "confirmed")
        self.assertEqual(transition["attributes_json"]["occurred_offset_ms"], 7500)

    def test_fast_change_gate_returns_only_change_decision(self):
        from PIL import Image
        import struct

        def jpeg(color):
            output = BytesIO()
            Image.new("RGB", (96, 54), color).save(output, format="JPEG")
            return output.getvalue()

        same = detect_frame_change((jpeg((40, 40, 40)), jpeg((40, 40, 40))))
        changed = detect_frame_change((jpeg((40, 40, 40)), jpeg((240, 240, 240))))
        self.assertFalse(same["changed"])
        self.assertTrue(changed["changed"])
        self.assertEqual(same["method"], "local_pixel_delta_plus_audio")

        silent = b"\x00\x00" * 16000
        loud = b"".join(struct.pack("<h", 16000 if index % 2 else -16000) for index in range(16000))
        audio_gate = detect_frame_change((jpeg((40, 40, 40)), jpeg((40, 40, 40))), audio_pcm=loud, previous_audio_level=0.0)
        self.assertTrue(audio_gate["changed"])
        self.assertIn("audio_energy_changed", audio_gate["change_reasons"])

    def test_change_gate_result_is_persisted_with_window_offsets(self):
        result = self.store.record_change_gate(
            stream_id="gate_run", window={"window_id": "gate_run:g1", "start_offset_ms": 0, "end_offset_ms": 5000},
            gate={"changed": True, "change_score": .42, "threshold": .045, "change_summary": "畫面有變化。", "change_reasons": ["pixel_delta_above_threshold"], "method": "local_pixel_delta"},
        )
        self.assertEqual((result["changed"], result["start_offset_ms"], result["end_offset_ms"]), (1, 0, 5000))
        self.assertEqual(self.store.change_gate_results(1)[0]["change_reasons_json"], ["pixel_delta_above_threshold"])


if __name__ == "__main__":
    unittest.main()
