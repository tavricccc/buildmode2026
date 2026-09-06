from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ..app import AppContext
from ..care_summary import build_care_summary
from ..config import AppConfig
from ..domain.enums import EventStatus, EventType
from ..domain.timeutil import now_ms
from ..media.replay_source import ReplaySource


class TestDebugSimulation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="care-debug-"))
        self.ctx = AppContext(AppConfig(runtime_mode="debug", data_dir=self.tmp), use_stubs=True)

    def tearDown(self) -> None:
        self.ctx.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_history_generator_builds_real_observer_summaries_and_is_idempotent(self):
        first = self.ctx.debug_simulator.generate_history(days=3, profile="mixed", seed=17)
        second = self.ctx.debug_simulator.generate_history(days=3, profile="mixed", seed=17)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "already_generated")
        self.assertEqual(first["simulation_id"], second["simulation_id"])
        self.assertEqual(len(self.ctx.repos.daily_summaries(10)), 3)
        self.assertTrue(self.ctx.repos.list_observer_runs(self.ctx.config.subject_id, 10))
        sources = self.ctx.db.query("SELECT DISTINCT source FROM health_samples")
        self.assertTrue(all(str(row["source"]).startswith("simulation:") for row in sources))

    def test_debug_config_uses_an_isolated_database(self):
        self.assertTrue(self.ctx.config.debug)
        self.assertEqual(self.ctx.config.db_path, self.tmp / "care.sqlite3")
        self.assertIsNotNone(self.ctx.debug_simulator)
        self.assertIsNone(self.ctx.notifier)

    def test_care_summary_surfaces_critical_and_recovering_states(self):
        stamp = now_ms()
        event_id, _ = self.ctx.repos.upsert_event(
            self.ctx.config.subject_id, EventType.fall, EventStatus.confirmed,
            "care-summary-test", stamp, 0.94, {}, "test.v1")
        self.ctx.repos.save_analysis(
            event_id, None, None, "test", ["possible_fall"], False,
            {"risk_level": "critical", "recommendation": "suggest_caregiver_notification",
             "supports_l2": True})
        critical = build_care_summary(self.ctx)
        self.assertEqual(critical["urgency"], "immediate")
        self.assertIn("強烈建議", critical["headline"])

        self.ctx.db.execute("DELETE FROM analyses WHERE event_id=?", (event_id,))
        self.ctx.repos.upsert_event(
            self.ctx.config.subject_id, EventType.fall, EventStatus.recovering,
            "care-summary-test", stamp, 0.9, {}, "test.v1")
        recovering = build_care_summary(self.ctx)
        self.assertEqual(recovering["state"], "recovering")
        self.assertEqual(recovering["urgency"], "watch")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_real_recording_eof_completes_and_stops_the_cascade(self):
        video = self.tmp / "short.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=gray:s=160x120:r=4",
            "-t", "0.8", "-pix_fmt", "yuv420p", str(video),
        ], check=True, timeout=15)
        self.ctx.start_source("replay_file", str(video))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and (
            self.ctx.source.health()["lifecycle"] == "running" or self.ctx.cascade._threads
        ):
            time.sleep(0.05)
        self.assertEqual(self.ctx.source.health()["lifecycle"], "completed")
        self.assertFalse(self.ctx.cascade._threads)
        failures = self.ctx.db.query(
            "SELECT * FROM pipeline_runs WHERE l2_outcome='failed'")
        self.assertEqual(failures, [])


class TestReplayLifecycle(unittest.TestCase):
    def test_normal_eof_is_completed(self):
        terminal: list[tuple[str, str | None]] = []
        done = threading.Event()
        source = ReplaySource("unused.mp4", on_terminal=lambda state, error: (terminal.append((state, error)), done.set()))
        source._pump = lambda sink: (0, None)  # type: ignore[method-assign]
        source.start(lambda packet: None)
        self.assertTrue(done.wait(2))
        self.assertEqual(source.health()["lifecycle"], "completed")
        self.assertEqual(terminal, [("completed", None)])
        source.stop()

    def test_nonzero_ffmpeg_exit_is_failed(self):
        done = threading.Event()
        source = ReplaySource("broken.mp4", on_terminal=lambda *_: done.set())
        source._pump = lambda sink: (1, "decode failed")  # type: ignore[method-assign]
        source.start(lambda packet: None)
        self.assertTrue(done.wait(2))
        self.assertEqual(source.health()["lifecycle"], "failed")
        self.assertEqual(source.health()["error"], "decode failed")
        source.stop()
