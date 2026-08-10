import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

import agentops_runtime.__main__ as cli
from agentops_runtime import setup_wizard as setup


GOOD_ID = "12345678-abcd-4abc-9abc-1234567890ab"
GOOD_URL = f"https://chatgpt.com/c/{GOOD_ID}"
OTHER_ID = "87654321-dcba-4cba-8cba-ba0987654321"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, url, timeout=0):
        self.calls.append((url, timeout))
        if url not in self.mapping:
            raise OSError("not found")
        return FakeResponse(self.mapping[url])


class TestConversationValidation(unittest.TestCase):
    def test_valid_conversation_is_canonicalized(self):
        raw = f"https://www.chatgpt.com/c/{GOOD_ID.upper()}/"
        self.assertEqual(setup.normalize_conversation_url(raw), GOOD_URL)
        self.assertEqual(setup.conversation_id_from_url(raw), GOOD_ID)

    def test_rejects_non_conversation_urls(self):
        invalid = [
            "https://chatgpt.com/",
            "https://chatgpt.com/share/abcdef",
            "https://chatgpt.com/g/g-abc-something",
            f"http://chatgpt.com/c/{GOOD_ID}",
            f"https://example.com/c/{GOOD_ID}",
            f"https://chatgpt.com/c/{GOOD_ID}?x=1",
            f"https://chatgpt.com/c/{GOOD_ID}#fragment",
            "https://chatgpt.com/c/not-a-valid-id",
        ]
        for url in invalid:
            with self.subTest(url=url):
                with self.assertRaises(setup.SetupError):
                    setup.normalize_conversation_url(url)

    def test_repository_validation(self):
        self.assertEqual(setup.normalize_repository("owner/repo"), "owner/repo")
        for value in ("repo", "owner/repo/extra", "https://github.com/o/r", "../o/r"):
            with self.subTest(value=value):
                with self.assertRaises(setup.SetupError):
                    setup.normalize_repository(value)


class TestConfigWriting(unittest.TestCase):
    def test_prepare_config_preserves_unrelated_fields(self):
        existing = {
            "custom": {"keep": True},
            "runtime": {"name": "My AgentOps", "cdp_port": 9233, "keep": "runtime"},
            "routes": {
                "owner/old": {
                    "conversation_url": f"https://chatgpt.com/c/{OTHER_ID}",
                    "cdp_port": 9233,
                    "keep": "route",
                }
            },
        }
        out = setup.prepare_config(
            existing, "owner/new", GOOD_URL, 9233, "~/agentops-profile")
        self.assertEqual(out["custom"], {"keep": True})
        self.assertEqual(out["runtime"]["name"], "My AgentOps")
        self.assertEqual(out["runtime"]["keep"], "runtime")
        self.assertEqual(out["routes"]["owner/old"]["keep"], "route")
        self.assertEqual(out["routes"]["owner/new"]["conversation_url"], GOOD_URL)
        self.assertEqual(out["routes"]["owner/new"]["cdp_port"], 9233)
        self.assertIn("runtime_marker", out["runtime"])

    def test_existing_different_route_port_fails_closed(self):
        existing = {
            "runtime": {"cdp_port": 9233},
            "routes": {"owner/old": {"conversation_url": GOOD_URL, "cdp_port": 9233}},
        }
        with self.assertRaises(setup.SetupError):
            setup.prepare_config(existing, "owner/new", GOOD_URL, 9444, "~/profile")

    def test_save_binding_is_atomic_enough_and_creates_marker(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = os.path.join(td, "relay", "config.json")
            profile = os.path.join(td, "profile")
            result = setup.save_binding(
                config_path, "owner/repo", GOOD_URL, 9233, profile)
            self.assertTrue(result["ok"])
            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
            self.assertEqual(config["routes"]["owner/repo"]["conversation_url"], GOOD_URL)
            self.assertEqual(config["runtime"]["browser_profile"], profile)
            marker_path = os.path.join(profile, "AGENTOPS_MARKER")
            self.assertTrue(os.path.exists(marker_path))
            with open(marker_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read().strip(), config["runtime"]["runtime_marker"])

    def test_generated_config_has_no_secret_fields(self):
        config = setup.prepare_config({}, "owner/repo", GOOD_URL, 9233, "~/profile")
        self.assertFalse(setup.generated_config_contains_secret_fields(config))
        serialized = json.dumps(config).lower()
        self.assertNotIn("password", serialized)
        self.assertNotIn("cookie", serialized)
        self.assertNotIn("api_key", serialized)


class TestExactTargetMatching(unittest.TestCase):
    def test_exact_single_target_passes(self):
        targets = [
            {"id": "wrong", "type": "page", "url": f"https://chatgpt.com/c/{OTHER_ID}"},
            {"id": "right", "type": "page", "url": GOOD_URL},
            {"id": "worker", "type": "service_worker", "url": GOOD_URL},
        ]
        out = setup.evaluate_targets(targets, GOOD_URL)
        self.assertTrue(out["ok"])
        self.assertEqual(out["matches"], 1)
        self.assertEqual(out["target_id"], "right")

    def test_zero_target_fails_closed(self):
        out = setup.evaluate_targets(
            [{"type": "page", "url": f"https://chatgpt.com/c/{OTHER_ID}"}], GOOD_URL)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "REVIEWER_CONVERSATION_NOT_FOUND")

    def test_duplicate_target_fails_closed(self):
        out = setup.evaluate_targets([
            {"id": "a", "type": "page", "url": GOOD_URL},
            {"id": "b", "type": "page", "url": GOOD_URL},
        ], GOOD_URL)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "AMBIGUOUS_REVIEWER_CONVERSATION")
        self.assertEqual(out["matches"], 2)

    def test_connection_probes_local_cdp(self):
        opener = FakeOpener({
            "http://127.0.0.1:9233/json/version": {
                "Browser": "Chrome/Test",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9233/devtools/browser/abc",
            },
            "http://127.0.0.1:9233/json": [
                {"id": "right", "type": "page", "url": GOOD_URL},
            ],
        })
        out = setup.test_connection(GOOD_URL, 9233, opener=opener)
        self.assertTrue(out["ok"])
        self.assertEqual(out["browser"], "Chrome/Test")
        self.assertEqual([call[0] for call in opener.calls], [
            "http://127.0.0.1:9233/json/version",
            "http://127.0.0.1:9233/json",
        ])

    def test_connection_unreachable_fails_closed(self):
        def broken(url, timeout=0):
            raise OSError("connection refused")

        out = setup.test_connection(GOOD_URL, 9233, opener=broken)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "CDP_UNREACHABLE")


class TestSetupServer(unittest.TestCase):
    def test_server_binds_loopback_only(self):
        with tempfile.TemporaryDirectory() as td:
            server, state, url = setup.create_setup_server(
                config_path=os.path.join(td, "config.json"),
                repository="owner/repo",
                setup_port=0,
                connection_tester=lambda url, port: {"ok": True},
            )
            try:
                self.assertEqual(server.server_address[0], "127.0.0.1")
                self.assertTrue(url.startswith("http://127.0.0.1:"))
                self.assertFalse(state["saved"])
            finally:
                server.server_close()

    def test_setup_page_has_no_credential_inputs(self):
        body = setup._render_page(
            {"repository": "owner/repo", "conversation_url": GOOD_URL,
             "cdp_port": "9233", "browser_profile": "~/profile"},
            "csrf", "/tmp/config.json")
        lower = body.lower()
        self.assertNotIn('name="password"', lower)
        self.assertNotIn('name="cookie"', lower)
        self.assertNotIn('name="token"', lower)
        self.assertIn("never asks for or stores", lower)

    def test_cli_setup_delegates_without_opening_when_requested(self):
        with mock.patch.object(setup, "run_setup", return_value=0) as run:
            rc = cli.main([
                "setup", "--repo", "owner/repo", "--no-open",
                "--config-file", "/tmp/agentops-test-config.json",
                "--cdp-port", "9233",
                "--browser-profile", "/tmp/agentops-profile",
            ])
        self.assertEqual(rc, 0)
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["repository"], "owner/repo")
        self.assertTrue(kwargs["no_open"])
        self.assertEqual(kwargs["cdp_port"], 9233)


if __name__ == "__main__":
    unittest.main()
