"""The scenarios v5 04 §必測情境 names, end to end.

Each test here maps to one line of that list. They run the real cascade
against the real SQLite schema with the stub model backends, so what is
under test is the routing, the state machines, the audit trail and the
Policy Gateway — everything except the network.
"""

import unittest

from ..domain.enums import EventStatus, EventType, L2Outcome, L3Outcome
from ..domain.policy import CadencePolicy, EscalationPolicy, NotificationPolicy
from ..l2.gemini_client import GeminiError
from ..l2.stub import StubL2Backend
from ..l3.minimax_client import MiniMaxError
from ..l3.stub import StubL3Backend
from .helpers import (
    DETECTOR_FAULT_SCENARIO,
    EMPTY_SCENARIO,
    FALL_SCENARIO,
    HYDRATION_SCENARIO,
    Harness,
    test_policy,
)


class CascadeCase(unittest.TestCase):
    harness: Harness

    def tearDown(self):
        if getattr(self, "harness", None) is not None:
            self.harness.close()


class TestEmptyRoom(CascadeCase):
    """空房：L1 大量 skip，但 heartbeat 仍有 Gemini call."""

    def test_most_windows_are_skipped_but_the_heartbeat_still_runs(self):
        self.harness = Harness(test_policy(
            cadence=CadencePolicy(l2_interval_sec=0.0, heartbeat_interval_sec=8.0,
                                  high_risk_interval_sec=0.0, window_seconds=4.0, clip_fps=4.0)))
        self.harness.play(EMPTY_SCENARIO)
        outcomes = self.harness.outcomes()

        skipped = outcomes.count(L2Outcome.skipped_l1.value)
        heartbeats = outcomes.count(L2Outcome.heartbeat.value)
        self.assertGreater(skipped, 0, "L1 must suppress normal calls in an empty room")
        self.assertGreater(heartbeats, 0, "a sparse safety heartbeat must survive the skip")
        self.assertGreater(skipped, heartbeats, "skipping is the point; the heartbeat is sparse")
        self.assertEqual(outcomes.count(L2Outcome.called.value), 0)

    def test_the_skip_ratio_is_visible_to_the_dashboard(self):
        self.harness = Harness()
        self.harness.play(EMPTY_SCENARIO)
        stats = self.harness.repos.run_stats(0)
        self.assertGreater(stats["skipped_by_l1"], 0)
        self.assertGreater(stats["skip_ratio"], 0.5)


class TestDetectorFault(CascadeCase):
    """L1 false negative / crash：fail-open."""

    def test_a_crashed_detector_does_not_read_as_an_empty_room(self):
        self.harness = Harness()
        self.harness.play(DETECTOR_FAULT_SCENARIO)
        runs = list(reversed(self.harness.repos.list_runs(limit=200)))
        faulted = [r for r in runs if r["l1_decision"] == "unavailable"]
        self.assertTrue(faulted, "the fault must surface as unavailable, not no_person")
        for run in faulted:
            self.assertNotEqual(run["l2_outcome"], L2Outcome.skipped_l1.value,
                                "an unavailable detector must never authorise a skip")

    def test_the_fall_is_still_caught_while_the_detector_is_down(self):
        self.harness = Harness()
        self.harness.play(DETECTOR_FAULT_SCENARIO)
        statuses = {status for _, status in self.harness.events()}
        self.assertTrue(statuses & {"confirmed", "recovering", "resolved", "suspect"},
                        f"expected a tracked fall, got {self.harness.events()}")


class TestFallBypassesL1(CascadeCase):
    """跌倒 suspect：繞過 L1，Gemini 持續 follow-up."""

    def test_high_risk_forces_calls_regardless_of_the_gate(self):
        self.harness = Harness()
        self.harness.play(FALL_SCENARIO)
        outcomes = self.harness.outcomes()
        self.assertGreater(outcomes.count(L2Outcome.forced_high_risk.value), 1,
                           "a tracked fall must keep pulling follow-up observations")

    def test_a_confirmed_fall_reaches_the_policy_gateway(self):
        self.harness = Harness()
        self.harness.play(FALL_SCENARIO)
        rules = [rule for _, rule, _ in self.harness.actions()]
        self.assertIn("fall_confirmed", rules)

    def test_hydration_does_not_trigger_the_high_risk_bypass(self):
        # v5 00 item 8 names fall specifically. Nobody is harmed by
        # learning about a glass of water four seconds late.
        self.harness = Harness()
        self.harness.play(HYDRATION_SCENARIO)
        self.assertEqual(self.harness.outcomes().count(L2Outcome.forced_high_risk.value), 0)


class TestEscalation(CascadeCase):
    """Gemini escalation：MiniMax 確實收到影片 + 文字."""

    def test_minimax_receives_frames_and_the_structured_reading(self):
        self.harness = Harness()
        self.harness.play(FALL_SCENARIO)
        self.assertGreater(self.harness.l3_backend.last_frame_count, 0,
                           "L3 must see the clip, not only a summary")
        analyses = self.harness.db.query("SELECT * FROM analyses")
        self.assertTrue(analyses)
        self.assertEqual(analyses[0]["degraded"], 0)

    def test_l3_is_not_called_for_routine_windows(self):
        self.harness = Harness()
        self.harness.play(HYDRATION_SCENARIO)
        outcomes = [r["l3_outcome"] for r in self.harness.repos.list_runs(limit=200)]
        self.assertEqual(set(outcomes), {L3Outcome.not_required.value},
                         "L3 is for escalations, not every window")

    def test_escalation_rate_limiting_is_recorded_with_its_reason(self):
        self.harness = Harness(test_policy(
            escalation=EscalationPolicy(min_seconds_between=10_000)))
        self.harness.play(FALL_SCENARIO)
        reasons = [r["l3_reason"] for r in self.harness.repos.list_runs(limit=200)]
        self.assertTrue(any("rate_limited" in reason for reason in reasons))

    def test_the_daily_cap_stops_runaway_spending(self):
        self.harness = Harness(test_policy(
            escalation=EscalationPolicy(min_seconds_between=0, max_per_day=1)))
        self.harness.play(FALL_SCENARIO)
        called = [r for r in self.harness.repos.list_runs(limit=200)
                  if r["l3_outcome"] in {L3Outcome.called.value,
                                         L3Outcome.degraded_text_only.value}]
        self.assertEqual(len(called), 1)
        reasons = [r["l3_reason"] for r in self.harness.repos.list_runs(limit=200)]
        self.assertTrue(any("daily_cap_reached" in reason for reason in reasons))


class TestFailureIsolation(CascadeCase):
    """MiniMax timeout：主事件管線不被卡死 · Gemini timeout：事件標 degraded."""

    def test_a_minimax_timeout_leaves_events_and_sqlite_working(self):
        self.harness = Harness(l3_backend=StubL3Backend(
            latency_ms=0, fail_with=MiniMaxError("timeout", "no response")))
        self.harness.play(FALL_SCENARIO)

        self.assertTrue(self.harness.events(), "events must still be produced")
        rules = [rule for _, rule, _ in self.harness.actions()]
        self.assertIn("fall_confirmed", rules, "deterministic policy must still fire")
        failures = [r for r in self.harness.repos.list_runs(limit=200)
                    if r["l3_outcome"] == L3Outcome.failed.value]
        self.assertTrue(failures)
        self.assertIn("timeout", failures[0]["l3_error"])

    def test_a_gemini_timeout_does_not_look_like_a_safe_window(self):
        self.harness = Harness(l2_backend=StubL2Backend(
            latency_ms=0, fail_with=GeminiError("timeout", "no response")))
        self.harness.play(FALL_SCENARIO)

        runs = self.harness.repos.list_runs(limit=200)
        failed = [r for r in runs if r["l2_outcome"] == L2Outcome.failed.value]
        self.assertTrue(failed)
        self.assertEqual(self.harness.events(), [],
                         "a window we could not read must not update event state")
        for run in failed:
            self.assertEqual(run["l3_outcome"], L3Outcome.not_required.value)
            self.assertEqual(run["l3_reason"], "no_valid_observation")

    def test_an_invalid_observation_is_recorded_and_changes_nothing(self):
        self.harness = Harness(l2_backend=StubL2Backend(latency_ms=0, malformed=True))
        # The stub repairs on the second attempt, so this must succeed *and*
        # be marked as repaired rather than silently accepted.
        self.harness.play(FALL_SCENARIO)
        repaired = [r for r in self.harness.repos.list_runs(limit=200) if r["l2_repaired"]]
        self.assertTrue(repaired)


class TestAuditTrail(CascadeCase):
    """v5 00 item 10: any window must be fully reconstructible."""

    def test_every_window_records_the_whole_path(self):
        self.harness = Harness()
        self.harness.play(FALL_SCENARIO)
        for run in self.harness.repos.list_runs(limit=200):
            self.assertIn(run["l1_decision"], {"person_present", "no_person", "stale", "unavailable"})
            self.assertIn(run["l2_outcome"], {o.value for o in L2Outcome})
            self.assertIn(run["l3_outcome"], {o.value for o in L3Outcome})
            self.assertTrue(run["config_version"])
            if run["l2_outcome"] in {"called", "heartbeat", "forced_high_risk"}:
                self.assertTrue(run["l2_call_id"], "a call must leave provenance")
                self.assertTrue(run["clip_path"], "a call must reference its evidence")

    def test_an_event_can_be_traced_back_to_its_windows(self):
        self.harness = Harness()
        self.harness.play(FALL_SCENARIO)
        events = self.harness.repos.list_events(limit=1)
        self.assertTrue(events)
        runs = self.harness.repos.runs_for_event(events[0]["event_id"])
        self.assertTrue(runs, "event_runs must link the event to the windows that made it")

    def test_replaying_the_same_footage_does_not_double_count(self):
        """v5 00 item 11: replay reset must be idempotent."""
        self.harness = Harness()
        self.harness.play(HYDRATION_SCENARIO)
        first = self.harness.repos.hydration_summary()

        self.harness.cascade.tracked[EventType.hydration].status = EventStatus.idle
        self.harness.play(HYDRATION_SCENARIO)
        second = self.harness.repos.hydration_summary()
        self.assertGreaterEqual(second["sessions"], first["sessions"])
        events = [e for e in self.harness.repos.list_events(limit=50)
                  if e["event_type"] == "hydration"]
        keys = [e["dedup_key"] for e in events]
        self.assertEqual(len(keys), len(set(keys)), "dedup keys must be unique")


class TestNotificationSuppression(CascadeCase):
    def test_an_unconfigured_telegram_downgrades_instead_of_failing_silently(self):
        self.harness = Harness(telegram_configured=False)
        self.harness.play(FALL_SCENARIO)
        confirmed = [a for a in self.harness.actions() if a[1] == "fall_confirmed"]
        self.assertTrue(confirmed)
        self.assertEqual(confirmed[0][0], "dashboard_alert")
        self.assertEqual(confirmed[0][2], "telegram_not_configured")

    def test_l3_cannot_notify_unless_the_operator_authorised_it(self):
        self.harness = Harness(test_policy(
            notification=NotificationPolicy(telegram_enabled=True,
                                            notify_on_l3_high_risk=False)))
        self.harness.play(FALL_SCENARIO)
        advisory = [a for a in self.harness.actions() if a[1] == "l3_advisory_not_authorised"]
        self.assertTrue(advisory)
        self.assertTrue(all(kind == "dashboard_alert" for kind, _, _ in advisory))


if __name__ == "__main__":
    unittest.main()
