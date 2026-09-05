"""HTTP + WebSocket surface (v5 03).

Boots the real server on an ephemeral port against a temporary data
directory, so the routes, the JSON envelope, the static fallback and the
RFC 6455 upgrade are all exercised as a client sees them.
"""

import base64
import copy
import json
import os
import shutil
import socket
import struct
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ..api.server import serve
from ..api.ws import accept_key, encode_frame
from ..app import AppContext
from ..config import AppConfig


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="care-api-"))
        replays = cls.tmp / "replays"
        replays.mkdir(parents=True)
        (replays / "fall.json").write_text(json.dumps({
            "name": "fall", "segments": [
                {"duration_sec": 4, "person": True, "posture": "standing"},
                {"duration_sec": 8, "person": True, "posture": "lying",
                 "near_floor": True, "motionless": True},
            ]}), encoding="utf-8")

        os.environ["CARE_DATA_DIR"] = str(cls.tmp)
        config = AppConfig()
        config.host, config.port = "127.0.0.1", free_port()
        cls.ctx = AppContext(config, use_stubs=True)
        cls.server = serve(cls.ctx)
        cls.base = f"http://127.0.0.1:{config.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.ctx.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        os.environ.pop("CARE_DATA_DIR", None)

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())


class TestReadEndpoints(ApiTestCase):
    def test_status_reports_all_three_layers(self):
        status, payload = self.call("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertIn("l1", payload["cascade"])
        self.assertIn("l2", payload["cascade"])
        self.assertIn("l3", payload["cascade"])
        self.assertEqual(payload["config_version"], self.ctx.policy.version)

    def test_status_never_leaks_a_secret_value(self):
        self.call("POST", "/api/secrets",
                  {"key": "GEMINI_API_KEY", "value": "AIzaSyLEAKCANARY123456"})
        for path in ("/api/status", "/api/settings"):
            _, payload = self.call("GET", path)
            self.assertNotIn("AIzaSyLEAKCANARY", json.dumps(payload))
        self.call("POST", "/api/secrets", {"key": "GEMINI_API_KEY", "value": ""})

    def test_setup_state_lists_what_is_still_missing(self):
        _, payload = self.call("GET", "/api/setup/state")
        ids = {step["id"] for step in payload["steps"]}
        self.assertEqual(ids, {"runtime", "storage", "l1", "l2", "l3", "source"})
        self.assertIn("fall", payload["scenarios"])

    def test_unknown_routes_return_a_structured_error(self):
        status, payload = self.call("GET", "/api/nope")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_a_bad_query_value_is_rejected_rather_than_ignored(self):
        status, payload = self.call("GET", "/api/pipeline/runs?l2_outcome=nonsense")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_outcome")

    def test_non_api_paths_fall_back_to_the_dashboard_page(self):
        with urllib.request.urlopen(self.base + "/dashboard", timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])


class TestCascadeThroughHttp(ApiTestCase):
    def test_cascade_test_runs_one_window_through_every_layer(self):
        status, payload = self.call("POST", "/api/pipeline/cascade-test", {"scenario": "fall"})
        self.assertEqual(status, 200)
        self.assertIn(payload["l1"]["decision"],
                      {"person_present", "no_person", "stale", "unavailable"})
        self.assertEqual(payload["l2"]["outcome"], "called")
        self.assertEqual(len(payload["trace"]), 3)
        self.assertEqual([step["layer"] for step in payload["trace"]], ["L1", "L2", "L3"])

    def test_a_missing_scenario_is_a_404_not_a_crash(self):
        status, payload = self.call("POST", "/api/pipeline/cascade-test", {"scenario": "ghost"})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "no_scenario")

    def test_runs_are_queryable_after_a_cascade_test(self):
        self.call("POST", "/api/pipeline/cascade-test", {"scenario": "fall"})
        status, payload = self.call("GET", "/api/pipeline/runs?limit=10")
        self.assertEqual(status, 200)
        self.assertTrue(payload["runs"])
        self.assertIn("skip_ratio", payload["stats"])

    def test_an_event_exposes_its_full_cascade_trace(self):
        for _ in range(3):
            self.call("POST", "/api/pipeline/cascade-test", {"scenario": "fall"})
        _, listed = self.call("GET", "/api/events")
        if not listed["events"]:
            self.skipTest("no event produced by this fixture")
        event_id = listed["events"][0]["event_id"]
        status, payload = self.call("GET", f"/api/events/{event_id}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["event"]["event_id"], event_id)
        self.assertIn("runs", payload)
        self.assertIn("model_calls", payload)

    def test_probing_an_unconfigured_provider_says_so(self):
        status, payload = self.call("POST", "/api/integrations/gemini/test")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "not_configured")


class TestSettings(ApiTestCase):
    def test_applying_settings_creates_a_new_rollbackable_version(self):
        _, before = self.call("GET", "/api/settings")
        original = copy.deepcopy(before["policy"])
        payload = copy.deepcopy(before["policy"])
        payload["fall"]["min_confidence"] = 0.75
        status, applied = self.call("PUT", "/api/settings", {"policy": payload, "note": "stricter"})
        self.assertEqual(status, 200)
        self.assertEqual(applied["policy"]["fall"]["min_confidence"], 0.75)
        self.assertNotEqual(applied["version"], original["version"])

        status, rolled = self.call("POST", "/api/settings/rollback",
                                   {"version": original["version"]})
        self.assertEqual(status, 200)
        self.assertEqual(rolled["policy"]["fall"]["min_confidence"],
                         original["fall"]["min_confidence"])

    def test_rolling_back_to_an_unknown_version_is_a_404(self):
        status, payload = self.call("POST", "/api/settings/rollback", {"version": "policy.vX"})
        self.assertEqual(status, 404)

    def test_an_unknown_secret_name_is_refused(self):
        status, payload = self.call("POST", "/api/secrets", {"key": "AWS_KEY", "value": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "unknown_secret")

    def test_malformed_json_is_a_400_not_a_500(self):
        request = urllib.request.Request(self.base + "/api/settings", data=b"{not json",
                                         method="PUT")
        request.add_header("Content-Type", "application/json")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 400)


class TestWebSocket(ApiTestCase):
    def test_handshake_and_push(self):
        sock = socket.create_connection(("127.0.0.1", self.ctx.config.port), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(
            f"GET /ws HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = sock.recv(1)
            self.assertTrue(chunk, "connection closed during handshake")
            header += chunk
        self.assertIn(b"101 Switching Protocols", header)
        self.assertIn(accept_key(key).encode(), header)

        self.call("POST", "/api/pipeline/cascade-test", {"scenario": "fall"})

        def recv_exact(count):
            buffer = b""
            while len(buffer) < count:
                chunk = sock.recv(count - len(buffer))
                if not chunk:
                    return None
                buffer += chunk
            return buffer

        head = recv_exact(2)
        self.assertIsNotNone(head)
        length = head[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", recv_exact(8))[0]
        message = json.loads(recv_exact(length))
        self.assertIn("topic", message)
        self.assertIn("seq", message)
        sock.close()

    def test_a_plain_get_on_ws_is_rejected(self):
        status, payload = self.call("GET", "/ws")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_upgrade")


if __name__ == "__main__":
    unittest.main()
