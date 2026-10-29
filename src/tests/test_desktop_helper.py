"""Route engine tests. They run against a local fake relay and a throwaway state folder."""
import importlib.util
import json
import os
import shutil
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "engine" / "desktop-helper.py"
SCRATCH = Path(os.environ.get("CODEX_ROUTE_TEST_TMP", str(Path(tempfile.gettempdir()) / "codex-route-tests")))
GOOD_KEY = "sk-test-0123456789"


class FakeRelay(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeRelay.seen.append({"path": self.path, "agent": self.headers.get("User-Agent", "")})
        if self.path == "/v1/models" and self.headers.get("Authorization") == "Bearer " + GOOD_KEY:
            body = json.dumps({"data": [{"id": "gpt-6.1-sol"}, {"id": "a-model"}, {"id": "a-model"}, {"nope": 1}]}).encode()
            self.send_response(200)
        elif self.path == "/v1/models":
            body = b'{"error":"bad key"}'
            self.send_response(401)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def load_helper():
    spec = importlib.util.spec_from_file_location("desktop_helper_under_test", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RouteEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeRelay)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeRelay.seen.clear()
        self.home = SCRATCH / uuid.uuid4().hex
        self.home.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.home, True)
        self.helper = load_helper()
        self.helper.ROOT = self.home

    def call(self, op, **args):
        return self.helper.dispatch({"operation": op, "args": args})

    def save_relay(self, rid="r1", key=GOOD_KEY):
        return self.call("save", id=rid, name="测试站", baseUrl=self.base, model="gpt-6.1-sol", key=key)

    def test_models_for_unsaved_draft_is_sorted_deduplicated_and_never_echoes_the_key(self):
        result = self.call("models", id="relay-123", baseUrl=self.base, key=GOOD_KEY)
        self.assertTrue(result["ok"])
        self.assertEqual(result["models"], ["a-model", "gpt-6.1-sol"])
        self.assertNotIn(GOOD_KEY, json.dumps(result))
        self.assertTrue(FakeRelay.seen[0]["agent"].startswith("codex-route-switch/"))

    def test_models_reports_bad_key_without_leaking_it(self):
        result = self.call("models", baseUrl=self.base, key="sk-wrong")
        self.assertFalse(result["ok"])
        self.assertIn("401", result["detail"])
        self.assertNotIn("sk-wrong", json.dumps(result))

    def test_models_hints_at_the_v1_suffix_on_404(self):
        result = self.call("models", baseUrl=self.base.replace("/v1", "/nowhere"), key=GOOD_KEY)
        self.assertFalse(result["ok"])
        self.assertIn("/v1", result["detail"])

    def test_models_requires_address_and_key(self):
        with self.assertRaises(ValueError):
            self.call("models", baseUrl="", key=GOOD_KEY)
        with self.assertRaises(ValueError):
            self.call("models", baseUrl=self.base, key="")

    def test_models_for_saved_route_uses_the_stored_key(self):
        self.save_relay()
        result = self.call("models", id="r1")
        self.assertTrue(result["ok"])
        self.assertIn("gpt-6.1-sol", result["models"])

    def test_check_finds_the_selected_model(self):
        self.save_relay()
        result = self.call("check", id="r1")
        self.assertTrue(result["ok"])
        self.assertIn("已找到所选模型", result["detail"])

    def test_snapshot_never_contains_the_key(self):
        snapshot = self.save_relay()
        self.assertNotIn(GOOD_KEY, json.dumps(snapshot))
        row = next(p for p in snapshot["providers"] if p["id"] == "r1")
        self.assertTrue(row["hasCredential"])

    def test_remove_resets_selection_to_official_and_keeps_a_backup(self):
        self.save_relay()
        self.call("select", id="r1")
        snapshot = self.call("remove", id="r1")
        self.assertEqual(snapshot["activeProfile"], "official")
        self.assertEqual([p["id"] for p in snapshot["providers"]], ["official"])
        self.assertTrue((self.home / "profiles.json.bak").exists())
        self.assertFalse((self.home / "credentials" / "r1.dpapi").exists())
        self.assertTrue((self.home / "credentials" / "r1.dpapi.removed").exists())

    def test_save_keeps_every_fetched_model_with_the_default_first(self):
        snapshot = self.call("save", id="r1", name="测试站", baseUrl=self.base, model="gpt-6.1-sol", key=GOOD_KEY,
                             models=["a-model", "b-model", "a-model", " b-model "])
        row = next(p for p in snapshot["providers"] if p["id"] == "r1")
        self.assertEqual(row["models"], ["gpt-6.1-sol", "a-model", "b-model"])
        self.assertEqual(row["model"], "gpt-6.1-sol")

    def test_routes_saved_before_model_lists_still_offer_their_default(self):
        self.save_relay()
        profiles = json.loads((self.home / "profiles.json").read_text(encoding="utf-8"))
        for profile in profiles["profiles"]:
            profile.pop("models", None)
        (self.home / "profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
        row = next(p for p in self.call("list")["providers"] if p["id"] == "r1")
        self.assertEqual(row["models"], ["gpt-6.1-sol"])

    def test_save_rejects_malformed_model_lists(self):
        for models in ("gpt", ["x" * 129], ["bad\nname"], ["m"] * 501):
            with self.assertRaises(ValueError):
                self.call("save", id="r1", name="测试站", baseUrl=self.base, model="gpt-6.1-sol", key=GOOD_KEY, models=models)

    def test_launch_hands_the_relay_model_list_to_the_bridge(self):
        self.call("save", id="r1", name="测试站", baseUrl=self.base, model="gpt-6.1-sol", key=GOOD_KEY, models=["a-model"])
        seen = {}

        class Done:
            returncode, stderr, stdout = 0, b"", b'{"pid":4242}\n'

        def fake_run(command, env, **kwargs):
            seen.update(env)
            return Done()

        self.addCleanup(setattr, self.helper.subprocess, "run", self.helper.subprocess.run)
        self.helper.subprocess.run = fake_run
        self.call("launch", id="r1")
        self.assertEqual(json.loads(seen["CODEX_ROUTE_MODELS"]), ["gpt-6.1-sol", "a-model"])
        self.assertEqual(seen["CODEX_ROUTE_MODEL"], "gpt-6.1-sol")
        launched = json.loads((self.home / "desktop-launch.json").read_text(encoding="utf-8"))
        self.assertEqual(launched["profileId"], "r1")

    def test_remove_refuses_official_and_unknown_routes(self):
        with self.assertRaises(ValueError):
            self.call("remove", id="official")
        with self.assertRaises(ValueError):
            self.call("remove", id="ghost")


if __name__ == "__main__":
    unittest.main()
