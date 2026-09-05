"""Telegram delivery and acknowledgement (docs/02_DATA_AND_POLICY.md §Telegram)."""

import shutil
import tempfile
import unittest
from pathlib import Path

from ..domain.enums import ActionKind, EventStatus, EventType
from ..notify.telegram import TelegramError, TelegramNotifier
from ..policy.gateway import PolicyDecision
from ..store import Database, Repositories, migrate


class FakeTelegram(TelegramNotifier):
    """Notifier with the network replaced, so the logic is what is tested."""

    def __init__(self, *args, fail: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent: list[dict] = []
        self.answers: list[str] = []
        self.fail = fail

    def _call(self, method, payload, timeout=None):
        if method == "sendMessage":
            if self.fail:
                raise TelegramError("http_403", "bot was blocked by the user")
            self.sent.append(payload)
            return {"message_id": len(self.sent)}
        if method == "answerCallbackQuery":
            self.answers.append(payload["text"])
            return {}
        return {}


def decision(event_id: str):
    return PolicyDecision(kind=ActionKind.notify_telegram, reason="Fall confirmed",
                          rule="fall_confirmed", severity="critical", event_id=event_id)


class TestTelegram(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="care-tg-"))
        self.db = Database(self.tmp / "care.sqlite3")
        migrate(self.db)
        self.repos = Repositories(self.db)
        self.event_id, _ = self.repos.upsert_event(
            "s", EventType.fall, EventStatus.confirmed, "s:fall:1", 1, 0.9, {}, "obs.window.v1")
        self.notifier = FakeTelegram("123:token", ("555",), self.repos)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def send(self):
        target = decision(self.event_id)
        self.repos.save_action(target, None)
        ids = self.notifier.dispatch(target, {"event_type": "fall", "status": "confirmed"})
        token = self.notifier.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        return ids[0], token.split(":", 1)[1]

    def test_a_token_and_no_chat_is_not_configured(self):
        self.assertFalse(TelegramNotifier("123:token", (), self.repos).configured)
        self.assertTrue(self.notifier.configured)

    def test_the_button_payload_carries_no_event_id(self):
        _, token = self.send()
        message = self.notifier.sent[-1]
        self.assertNotIn(self.event_id, str(message["reply_markup"]))
        self.assertGreaterEqual(len(token), 20)

    def test_acknowledgement_records_who_answered(self):
        delivery_id, token = self.send()
        self.assertTrue(self.notifier.handle_callback({
            "id": "cb1", "data": f"ack:{token}", "message": {"chat": {"id": 555}}}))
        row = self.db.query_one("SELECT status FROM notification_deliveries WHERE delivery_id=?",
                                (delivery_id,))
        self.assertEqual(row["status"], "acknowledged")

    def test_a_false_alarm_is_a_distinct_outcome(self):
        delivery_id, token = self.send()
        self.notifier.handle_callback({"id": "cb", "data": f"nak:{token}",
                                       "message": {"chat": {"id": 555}}})
        row = self.db.query_one("SELECT status FROM notification_deliveries WHERE delivery_id=?",
                                (delivery_id,))
        self.assertEqual(row["status"], "false_alarm")

    def test_a_token_is_single_use(self):
        _, token = self.send()
        payload = {"id": "cb", "data": f"ack:{token}", "message": {"chat": {"id": 555}}}
        self.assertTrue(self.notifier.handle_callback(payload))
        self.assertFalse(self.notifier.handle_callback(payload))
        self.assertIn("Already recorded as acknowledged.", self.notifier.answers)

    def test_a_chat_outside_the_allowlist_is_ignored_in_silence(self):
        _, token = self.send()
        self.assertFalse(self.notifier.handle_callback({
            "id": "cb", "data": f"ack:{token}", "message": {"chat": {"id": 999}}}))
        self.assertEqual(self.notifier.answers, [],
                         "answering would confirm this bot serves this deployment")

    def test_an_unknown_token_changes_nothing(self):
        self.send()
        self.assertFalse(self.notifier.handle_callback({
            "id": "cb", "data": "ack:not-a-real-token", "message": {"chat": {"id": 555}}}))

    def test_a_send_failure_is_recorded_rather_than_lost(self):
        failing = FakeTelegram("123:token", ("555",), self.repos, fail=True)
        target = decision(self.event_id)
        self.repos.save_action(target, None)
        delivery_ids = failing.dispatch(target, None)
        row = self.db.query_one("SELECT status, error FROM notification_deliveries WHERE delivery_id=?",
                                (delivery_ids[0],))
        self.assertEqual(row["status"], "failed")
        self.assertIn("http_403", row["error"])


if __name__ == "__main__":
    unittest.main()
