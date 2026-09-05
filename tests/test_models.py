import json
import tempfile
import unittest
from pathlib import Path

from capture.models import EventCandidate, MultimodalEventBundle


class EventModelTests(unittest.TestCase):
    def test_candidate_has_traceable_ids_and_window(self):
        candidate = EventCandidate.start("resident_001", "test-source")
        candidate.finish()
        payload = candidate.to_dict()

        self.assertTrue(payload["event_id"].startswith("evt_"))
        self.assertTrue(payload["correlation_id"].startswith("corr_"))
        self.assertEqual(payload["window"]["start"], payload["occurred_at"])
        self.assertIsNotNone(payload["window"]["end"])

    def test_bundle_serializes_contract(self):
        candidate = EventCandidate.start("resident_001", "test-source")
        candidate.finish()
        bundle = MultimodalEventBundle(
            candidate=candidate,
            modalities={"audio": {"status": "pending"}, "video": {"status": "pending"}},
            quality={"missing_modalities": []},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bundle.json"
            bundle.write_json(path)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "multimodal_event_bundle.v1")
        self.assertEqual(payload["event"]["subject_id"], "resident_001")
        self.assertIn("provenance", payload)
        self.assertIn("audio", payload["modalities"])


if __name__ == "__main__":
    unittest.main()

