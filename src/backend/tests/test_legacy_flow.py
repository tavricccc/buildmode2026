"""Regression tests for the original-flow compatibility layer."""

import shutil
import tempfile
import unittest
from pathlib import Path

from ..legacy_flow import LegacyFlow
from ..store import Database, Repositories, migrate


class TestLegacyFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="care-legacy-flow-"))
        self.db = Database(self.tmp / "care.sqlite3")
        migrate(self.db)
        self.repos = Repositories(self.db)
        self.flow = LegacyFlow(self.repos, "subject-1", use_stub=True)

    def tearDown(self):
        self.flow.shutdown()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_interaction_preserves_explicit_memory_as_pending(self):
        result = self.flow.interaction("請記得我喜歡安靜的提醒。", "c1")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["intent"], "preference_statement")
        memories = self.repos.list_memories("subject-1", "pending")
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["status"], "pending")

    def test_main_agent_is_audited_without_direct_action(self):
        result = self.flow.run_main_agent(
            window={"window_id": "w1", "frame_count": 2},
            observation={"person_visible": True, "confidence": 0.8},
        )
        self.assertEqual(result["status"], "completed")
        runs = self.repos.list_agent_runs(agent_name="main_agent")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["output"]["proposed_action"], "observe")

    def test_simple_greeting_does_not_reuse_previous_turn(self):
        result = LegacyFlow._normalise_reply(
            {"reply_text": "好的，我現在就提醒您慢慢喝水。", "intent": "conversation"}, "hi"
        )
        self.assertEqual(result["intent"], "conversation")
        self.assertIn("您好", result["reply_text"])
        self.assertNotIn("喝水", result["reply_text"])


if __name__ == "__main__":
    unittest.main()
