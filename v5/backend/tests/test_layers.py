"""L2 and L3 services: repair, failure and degradation (v5 01)."""

import json
import unittest

from ..domain.enums import EscalationTrigger, L3Outcome
from ..domain.l3_contract import EvidenceBundle, VideoClip
from ..l2.gemini_client import GeminiError, GeminiResponse
from ..l2.service import L2Service
from ..l2.stub import StubL2Backend
from ..l3.minimax_client import MiniMaxClient, MiniMaxError, _thin
from ..l3.service import L3Service
from ..l3.stub import StubL3Backend

CLIP = VideoClip("/tmp/none.mp4", "video/mp4", 8.0, 2048, 0, 32)


class RecordingBackend(StubL2Backend):
    """Stub that returns a scripted sequence of raw texts."""

    def __init__(self, texts):
        super().__init__(latency_ms=0)
        self.texts = list(texts)
        self.prompts = []

    def generate(self, parts, **kwargs):
        self.calls += 1
        self.prompts.append(" ".join(p.get("text", "") for p in parts if "text" in p))
        text = self.texts.pop(0) if self.texts else "{}"
        return GeminiResponse(text=text, latency_ms=1, model=self.model, finish_reason="STOP")


class TestL2(unittest.TestCase):
    def test_valid_output_needs_one_call(self):
        backend = StubL2Backend(latency_ms=0)
        result = L2Service(backend, provider="stub").observe(
            VideoClip("/tmp/none.mp4", "video/mp4", 8.0, 1, 0, 8,
                      annotation={"person": True, "posture": "standing"}))
        self.assertTrue(result.ok)
        self.assertEqual(result.call.status, "ok")
        self.assertEqual(backend.calls, 1)

    def test_a_schema_violation_is_repaired_exactly_once(self):
        good = json.dumps(StubL2Backend()._observation())
        backend = RecordingBackend(['{"person_visible": true, "confidence": 1.9}', good])
        result = L2Service(backend, provider="stub").observe(CLIP)
        self.assertTrue(result.ok)
        self.assertEqual(result.call.status, "repaired")
        self.assertEqual(result.call.attempts, 2)
        self.assertIn("Validator error", backend.prompts[1])

    def test_a_repair_that_also_fails_yields_invalid_not_a_guess(self):
        backend = RecordingBackend(["not json at all", "still not json"])
        result = L2Service(backend, provider="stub").observe(CLIP)
        self.assertFalse(result.ok)
        self.assertEqual(result.call.status, "invalid")
        self.assertEqual(result.call.error_code, "schema_invalid")
        self.assertEqual(backend.calls, 2)

    def test_a_transport_failure_is_not_repaired(self):
        # Retrying a timeout with a repair prompt only doubles the outage.
        backend = StubL2Backend(fail_with=GeminiError("timeout", "no response"))
        result = L2Service(backend, provider="stub").observe(CLIP)
        self.assertEqual(result.call.status, "failed")
        self.assertEqual(result.call.error_code, "timeout")
        self.assertEqual(backend.calls, 1)

    def test_a_truncated_response_is_not_repaired(self):
        class Truncating(RecordingBackend):
            def generate(self, parts, **kwargs):
                self.calls += 1
                return GeminiResponse(text='{"person_visible": tr', latency_ms=1,
                                      model=self.model, finish_reason="MAX_TOKENS")

        backend = Truncating([])
        result = L2Service(backend, provider="stub").observe(CLIP)
        self.assertEqual(result.call.error_code, "max_tokens")
        self.assertEqual(backend.calls, 1)

    def test_secrets_never_reach_the_audit_row(self):
        leaked = "AIzaSyLEAKED0000000000"
        backend = RecordingBackend([f"error, key {leaked} rejected", "nope"])
        service = L2Service(backend, provider="stub",
                            redact=lambda text: text.replace(leaked, "***redacted***"))
        result = service.observe(CLIP)
        self.assertNotIn(leaked, result.call.response_text or "")
        self.assertNotIn(leaked, result.call.error_message or "")

    def test_the_heartbeat_prompt_says_it_is_checking_an_empty_room(self):
        backend = RecordingBackend([json.dumps(StubL2Backend()._observation())])
        L2Service(backend, provider="stub").observe(CLIP, heartbeat=True)
        self.assertIn("believed the room was empty", backend.prompts[0])


class TestL3(unittest.TestCase):
    def bundle(self, clip=CLIP, reasons=("possible_fall",)):
        return EvidenceBundle(
            escalation_id="esc_1", trigger=EscalationTrigger.gemini_requested,
            reason_codes=list(reasons),
            l2_observation={"fall": {"posture": "lying", "motionless": True}},
            event_state={"fall": {"status": "suspect"}}, clip=clip,
        )

    def test_video_reaches_the_model(self):
        backend = StubL3Backend(latency_ms=0)
        result = L3Service(backend, provider="stub").analyse(self.bundle(), [b"jpeg"] * 20)
        self.assertEqual(result.outcome, L3Outcome.called)
        self.assertEqual(backend.last_frame_count, 20)
        self.assertTrue(result.ok)

    def test_a_missing_clip_is_recorded_as_degraded_not_hidden(self):
        result = L3Service(StubL3Backend(latency_ms=0), provider="stub").analyse(
            self.bundle(clip=None), [])
        self.assertEqual(result.outcome, L3Outcome.degraded_text_only)
        self.assertTrue(result.ok)
        self.assertIn("no footage attached", result.analysis.uncertainty)

    def test_text_only_can_be_forbidden_outright(self):
        result = L3Service(StubL3Backend(latency_ms=0), provider="stub").analyse(
            self.bundle(clip=None), [], allow_text_only=False)
        self.assertFalse(result.ok)
        self.assertEqual(result.call.error_code, "no_video_evidence")

    def test_a_timeout_returns_a_result_and_never_raises(self):
        """v5 00 item 9: L3 failing must not stop the pipeline."""
        service = L3Service(StubL3Backend(fail_with=MiniMaxError("timeout", "no response")),
                            provider="stub")
        result = service.analyse(self.bundle(), [b"jpeg"])
        self.assertFalse(result.ok)
        self.assertEqual(result.outcome, L3Outcome.failed)
        self.assertEqual(result.call.error_code, "timeout")

    def test_an_unexpected_exception_is_also_contained(self):
        class Exploding(StubL3Backend):
            def analyse(self, parts, **kwargs):
                raise RuntimeError("boom")

        result = L3Service(Exploding(), provider="stub").analyse(self.bundle(), [b"jpeg"])
        self.assertEqual(result.call.error_code, "unexpected_error")

    def test_the_prompt_says_outright_when_no_footage_is_attached(self):
        from ..l3.prompt import analysis_prompt

        self.assertIn("NO FOOTAGE IS ATTACHED", analysis_prompt(self.bundle(clip=None)))
        self.assertNotIn("NO FOOTAGE IS ATTACHED", analysis_prompt(self.bundle()))


class TestMiniMaxWire(unittest.TestCase):
    def test_frames_are_sampled_across_the_clip_not_from_its_tail(self):
        frames = [bytes([i]) for i in range(40)]
        picked = _thin(frames, 10)
        self.assertEqual(len(picked), 10)
        self.assertEqual(picked[0], frames[0])
        self.assertEqual(picked[-1], frames[-1])
        self.assertLess(picked[4][0], 30)

    def test_video_url_format_requires_a_reachable_url(self):
        client = MiniMaxClient("key", wire_format="video_url")
        with self.assertRaises(MiniMaxError):
            client.video_parts([b"jpeg"], clip_url=None)

    def test_an_empty_key_is_refused_before_any_request(self):
        with self.assertRaises(MiniMaxError):
            MiniMaxClient("")


if __name__ == "__main__":
    unittest.main()
