"""L1 person gate (v5 01 §L1, v5 00 items 3-5)."""

import unittest

from ..domain.enums import Health, L1Decision
from ..domain.l1_contract import PersonGateReading
from ..domain.policy import L1Policy
from ..l1.detector import MotionPersonDetector, OnnxPersonDetector, StubPersonDetector
from ..l1.gate import PersonGate
from ..media.frames import FramePacket
from ..media.replay_source import _TINY_JPEG


def frame(annotation=None, at_ms=0):
    return FramePacket(1, at_ms, _TINY_JPEG, 64, 64, "cam", "replay", annotation)


def reading(present, at_ms, confidence=0.9, health=Health.ok):
    return PersonGateReading.parse({
        "person_present": present, "confidence": confidence, "observed_at_ms": at_ms,
        "detector_id": "stub", "health": health.value,
    })


class TestHysteresis(unittest.TestCase):
    def setUp(self):
        self.gate = PersonGate(L1Policy(frames_to_enter=2, frames_to_exit=4))

    def test_cold_start_assumes_present(self):
        # With no evidence either way, "absent" would be the unsafe
        # default: the first healthy reading would authorise a skip and
        # bypass the exit hysteresis entirely.
        self.gate.observe(reading(False, 1000))
        self.assertEqual(self.gate.decide(1000).kind, L1Decision.person_present)

    def test_leaving_costs_more_readings_than_entering(self):
        for i in range(4):
            self.gate.observe(reading(False, 1000 + i * 100))
        self.assertEqual(self.gate.decide(1300).kind, L1Decision.no_person)

        self.gate.observe(reading(True, 1400))
        self.assertEqual(self.gate.decide(1400).kind, L1Decision.no_person)
        self.gate.observe(reading(True, 1500))
        self.assertEqual(self.gate.decide(1500).kind, L1Decision.person_present)

        for i in range(3):
            self.gate.observe(reading(False, 1600 + i * 100))
            self.assertEqual(self.gate.decide(1600 + i * 100).kind, L1Decision.person_present)
        self.gate.observe(reading(False, 1900))
        self.assertEqual(self.gate.decide(1900).kind, L1Decision.no_person)

    def test_low_confidence_present_does_not_enter(self):
        gate = PersonGate(L1Policy(confidence_threshold=0.8, frames_to_enter=2,
                                   frames_to_exit=4))
        for i in range(8):
            gate.observe(reading(True, 1000 + i * 100, confidence=0.4))
        self.assertEqual(gate.decide(1700).kind, L1Decision.no_person)

    def test_only_no_person_permits_a_skip(self):
        for kind in L1Decision:
            self.assertEqual(kind.permits_skip(), kind is L1Decision.no_person, kind)


class TestFailOpen(unittest.TestCase):
    """v5 00 item 5: a broken detector must never read as an empty room."""

    def setUp(self):
        self.gate = PersonGate(L1Policy(stale_after_ms=5000))

    def test_no_reading_yet_fails_open(self):
        decision = self.gate.decide(1000)
        self.assertEqual(decision.kind, L1Decision.unavailable)
        self.assertFalse(decision.permits_skip())

    def test_stale_reading_fails_open(self):
        for i in range(4):
            self.gate.observe(reading(False, 1000 + i * 100))
        self.assertTrue(self.gate.decide(1400).permits_skip())
        stale = self.gate.decide(1300 + 9999)
        self.assertEqual(stale.kind, L1Decision.stale)
        self.assertFalse(stale.permits_skip())

    def test_unavailable_detector_fails_open(self):
        self.gate.observe(reading(False, 1000, health=Health.unavailable))
        decision = self.gate.decide(1000)
        self.assertEqual(decision.kind, L1Decision.unavailable)
        self.assertFalse(decision.permits_skip())

    def test_degraded_detector_may_not_argue_the_room_empty(self):
        self.gate.observe(reading(False, 1000, health=Health.degraded))
        self.assertFalse(self.gate.decide(1000).permits_skip())

    def test_a_fault_clears_both_streaks(self):
        # Otherwise a detector failing repeatedly would accumulate an
        # "absent" streak and eventually flip the gate to no_person.
        for i in range(3):
            self.gate.observe(reading(True, 1000 + i * 100))
        self.gate.observe(reading(False, 1400, health=Health.unavailable))
        self.assertEqual(self.gate.metrics()["streak_present"], 0)
        self.assertEqual(self.gate.metrics()["streak_absent"], 0)

    def test_disabled_gate_means_always_look_not_never_look(self):
        gate = PersonGate(L1Policy(enabled=False))
        gate.observe(reading(False, 1000))
        self.assertFalse(gate.decide(1000).permits_skip())


class TestDetectors(unittest.TestCase):
    def test_stub_reports_a_fault_rather_than_absence(self):
        detector = StubPersonDetector()
        result = detector.detect(frame({"detector_fault": True}))
        self.assertEqual(result.health, Health.unavailable.value)

    def test_motion_detector_has_no_baseline_on_its_first_frame(self):
        detector = MotionPersonDetector()
        first = detector.detect(frame())
        self.assertEqual(first.health, Health.degraded.value)
        self.assertEqual(detector.detect(frame()).health, Health.ok.value)

    def test_missing_onnx_model_is_unavailable_not_absent(self):
        detector = OnnxPersonDetector(model_path="/nonexistent/yolo11n.onnx")
        self.assertEqual(detector.detect(frame()).health, Health.unavailable.value)
        self.assertEqual(detector.health()["status"], Health.unavailable.value)


if __name__ == "__main__":
    unittest.main()
