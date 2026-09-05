"""Policy Gateway, queue, persistence and secret handling (docs/02_DATA_AND_POLICY.md, 04)."""

import os
import shutil
import tempfile
import unittest
import os
from pathlib import Path

from ..cascade.queue import LayerQueue, QueuedJob
from ..domain.enums import ActionKind, EventStatus, EventType
from ..domain.l3_contract import DeeperAnalysis
from ..domain.policy import CarePolicy, NotificationPolicy
from ..domain.timeutil import now_ms
from ..policy import PolicyGateway, PolicyInput
from ..secretstore import SecretStore
from ..store import Database, Repositories, migrate


def analysis(risk="critical", recommendation="suggest_caregiver_notification"):
    return DeeperAnalysis.parse({"interpretation": "on the floor", "risk_level": risk,
                                 "recommendation": recommendation, "confidence": 0.9})


class TestPolicyGateway(unittest.TestCase):
    """docs/02_DATA_AND_POLICY.md: a model may argue for an action; only policy authorises one."""

    def gateway(self, **overrides):
        return PolicyGateway(NotificationPolicy(telegram_enabled=True, **overrides))

    def test_a_confirmed_fall_notifies(self):
        decisions = self.gateway().decide(PolicyInput(
            EventType.fall, EventStatus.confirmed, "e1", alert_due=True,
            alert_reason="fall_confirmed", telegram_configured=True, now_ms=0))
        self.assertEqual(decisions[0].kind, ActionKind.notify_telegram)
        self.assertFalse(decisions[0].suppressed)

    def test_rate_limiting_downgrades_and_records_why(self):
        decisions = self.gateway(min_seconds_between=300).decide(PolicyInput(
            EventType.fall, EventStatus.confirmed, "e1", alert_due=True,
            alert_reason="fall_confirmed", telegram_configured=True,
            now_ms=100_000, last_notified_at_ms=99_000))
        self.assertEqual(decisions[0].kind, ActionKind.dashboard_alert)
        self.assertIn("rate_limited", decisions[0].suppressed_reason)

    def test_an_unauthorised_l3_recommendation_surfaces_rather_than_vanishing(self):
        decisions = self.gateway(notify_on_l3_high_risk=False).decide(PolicyInput(
            EventType.fall, EventStatus.suspect, "e2", analysis=analysis(),
            telegram_configured=True, now_ms=0))
        self.assertEqual(decisions[0].kind, ActionKind.dashboard_alert)
        self.assertEqual(decisions[0].rule, "l3_advisory_not_authorised")
        self.assertIn("critical", decisions[0].reason)

    def test_an_authorised_l3_recommendation_may_notify(self):
        decisions = self.gateway(notify_on_l3_high_risk=True).decide(PolicyInput(
            EventType.fall, EventStatus.suspect, "e2", analysis=analysis(),
            telegram_configured=True, now_ms=0))
        self.assertEqual(decisions[0].kind, ActionKind.notify_telegram)

    def test_a_low_risk_analysis_never_reaches_a_notification_rule(self):
        decisions = self.gateway(notify_on_l3_high_risk=True).decide(PolicyInput(
            EventType.fall, EventStatus.suspect, "e2", analysis=analysis(risk="low"),
            telegram_configured=True, now_ms=0))
        self.assertEqual([d.rule for d in decisions], ["default"])

    def test_the_gateway_takes_no_recipient_from_a_model(self):
        # DeeperAnalysis has no recipient/channel field at all; this asserts
        # the contract itself, not just this call site.
        self.assertNotIn("recipient", DeeperAnalysis.fields)
        self.assertNotIn("channel", DeeperAnalysis.fields)
        self.assertNotIn("telegram_chat_id", DeeperAnalysis.fields)


class TestLayerQueue(unittest.TestCase):
    def test_a_newer_window_supersedes_an_older_pending_one(self):
        queue = LayerQueue("l2")
        queue.offer(QueuedJob("a", label="a"))
        accepted, reason = queue.offer(QueuedJob("b", label="b"))
        self.assertTrue(accepted)
        self.assertEqual(reason, "replaced_pending")
        self.assertEqual(queue.take(0.01).label, "b")

    def test_a_routine_window_cannot_evict_a_pending_fall_follow_up(self):
        queue = LayerQueue("l2")
        queue.offer(QueuedJob("fall", high_risk=True, label="fall"))
        accepted, reason = queue.offer(QueuedJob("routine", label="routine"))
        self.assertFalse(accepted)
        self.assertIn("high_risk", reason)
        self.assertEqual(queue.take(0.01).label, "fall")

    def test_high_risk_may_replace_high_risk(self):
        queue = LayerQueue("l2")
        queue.offer(QueuedJob("old", high_risk=True, label="old"))
        self.assertTrue(queue.offer(QueuedJob("new", high_risk=True, label="new"))[0])
        self.assertEqual(queue.take(0.01).label, "new")

    def test_drops_are_counted_not_hidden(self):
        dropped = []
        queue = LayerQueue("l2", on_drop=lambda job, reason: dropped.append(reason))
        queue.offer(QueuedJob("a", label="a"))
        queue.offer(QueuedJob("b", label="b"))
        self.assertEqual(queue.metrics()["dropped"], 1)
        self.assertEqual(dropped, ["superseded_by_newer_window"])


class TestSecretStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="care-secrets-"))
        self.store = SecretStore(self.tmp / "secrets.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_describe_never_contains_the_value(self):
        self.store.set("GEMINI_API_KEY", "AIzaSyREALKEY0000000000")
        described = self.store.describe()
        self.assertTrue(described["GEMINI_API_KEY"]["configured"])
        self.assertNotIn("AIzaSy", repr(described))

    def test_redaction_strips_every_configured_secret(self):
        self.store.set("GEMINI_API_KEY", "AIzaSyREALKEY0000000000")
        self.store.set("MINIMAX_API_KEY", "sk-minimax-abcdef123456")
        text = "failed for AIzaSyREALKEY0000000000 and sk-minimax-abcdef123456"
        redacted = self.store.redact(text)
        self.assertNotIn("AIzaSy", redacted)
        self.assertNotIn("sk-minimax", redacted)

    def test_unknown_keys_are_refused(self):
        with self.assertRaises(KeyError):
            self.store.set("SOME_OTHER_KEY", "x")

    @unittest.skipIf(os.name == "nt", "Windows ACLs do not expose POSIX mode bits")
    def test_the_file_is_not_world_readable(self):
        self.store.set("GEMINI_API_KEY", "x" * 20)
        if os.name == "nt":
            # Windows reports synthetic POSIX mode bits (commonly 0666) even
            # when the file inherits a user-scoped NTFS ACL. The chmod
            # assertion is meaningful only on POSIX filesystems.
            self.assertTrue((self.tmp / "secrets.json").is_file())
            return
        mode = (self.tmp / "secrets.json").stat().st_mode & 0o777
        self.assertEqual(mode & 0o077, 0, f"secrets.json is {oct(mode)}")

    def test_secrets_survive_a_reload(self):
        self.store.set("TELEGRAM_BOT_TOKEN", "123:abc")
        reloaded = SecretStore(self.tmp / "secrets.json")
        self.assertTrue(reloaded.configured("TELEGRAM_BOT_TOKEN"))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="care-store-"))
        self.db = Database(self.tmp / "care.sqlite3")
        self.applied = migrate(self.db)
        self.repos = Repositories(self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_migrations_are_idempotent(self):
        # Both branches added a 002. migrate() keys on filename and applies in
        # sorted filename order, so the duplicate number is cosmetic — but the
        # order below is the one the runner actually produces.
        self.assertEqual(self.applied, [
            "001_v5_initial.sql", "002_legacy_flow.sql",
            "002_observer_runs.sql", "003_observation_history.sql",
            "004_debug_and_pipeline_steps.sql",
            "004_social_work_reports.sql",
        ])
        self.assertEqual(migrate(self.db), [])

    def test_the_schema_has_the_v5_audit_table(self):
        tables = {row["name"] for row in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("pipeline_runs", tables)
        for carried_over in ("events", "evidence", "hydration_sessions", "health_samples",
                             "analyses", "actions", "transcripts", "daily_summaries",
                             "observer_findings", "notification_deliveries"):
            self.assertIn(carried_over, tables)

    def test_an_event_is_identified_by_its_dedup_key(self):
        first, created_first = self.repos.upsert_event(
            "s", EventType.fall, EventStatus.suspect, "s:fall:1", 1, 0.9, {}, "v1")
        second, created_second = self.repos.upsert_event(
            "s", EventType.fall, EventStatus.confirmed, "s:fall:1", 1, 0.95, {}, "v1")
        self.assertEqual(first, second)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(self.repos.get_event(first)["status"], "confirmed")

    def test_config_versions_support_rollback(self):
        self.repos.save_config_version("policy.v5.0", CarePolicy().to_dict(), "defaults")
        tuned = CarePolicy.from_dict({**CarePolicy().to_dict(),
                                      "fall": {"min_confidence": 0.8}}).with_version("policy.v5.1")
        self.repos.save_config_version(tuned.version, tuned.to_dict(), "stricter")
        self.assertEqual(self.repos.active_config()["version"], "policy.v5.1")

        self.assertTrue(self.repos.activate_config_version("policy.v5.0"))
        active = self.repos.active_config()
        self.assertEqual(active["version"], "policy.v5.0")
        self.assertEqual(CarePolicy.from_dict(active["payload"]).fall.min_confidence, 0.5)
        self.assertEqual(len(self.repos.list_config_versions()), 2)

    def test_transcripts_expire(self):
        # The TTL is relative to when the utterance ended, so an old
        # transcript is already past its expiry the moment it is stored.
        now = now_ms()
        self.repos.save_transcript("s", "expired", now - 7200_000, now - 7200_000, 0.9, ttl_sec=60)
        self.repos.save_transcript("s", "current", now - 1000, now, 0.9, ttl_sec=3600)
        self.assertEqual(self.repos.sweep_transcripts(), 1)
        self.assertEqual(self.repos.recent_transcript("s", now - 10_000), "current")

    def test_policy_round_trips_through_json(self):
        original = CarePolicy()
        restored = CarePolicy.from_dict(original.to_dict())
        self.assertEqual(restored.to_dict(), original.to_dict())

    def test_unknown_policy_keys_are_ignored_rather_than_crashing(self):
        payload = CarePolicy().to_dict()
        payload["fall"]["invented_threshold"] = 99
        payload["not_a_group"] = {"x": 1}
        self.assertEqual(CarePolicy.from_dict(payload).fall.min_confidence, 0.5)


if __name__ == "__main__":
    unittest.main()
