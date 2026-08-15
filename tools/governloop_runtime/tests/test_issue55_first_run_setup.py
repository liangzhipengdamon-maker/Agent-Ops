import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import cli
from governloop_runtime import setup_wizard


class TestIssue55FirstRunSetup(unittest.TestCase):
    def test_instructions_forbid_preflight_guesswork(self):
        text = cli.AGENT_INSTRUCTIONS
        self.assertIn("immediately run: governloop setup", text)
        self.assertIn("Do NOT preflight or invent Chrome commands", text)
        self.assertIn("If setup returns NEXT_REQUIRED_ACTION", text)
        self.assertIn("address exactly that one blocker", text)

    def test_existing_runtime_profile_is_preserved_when_not_overridden(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = os.path.join(td, "config.json")
            profile = os.path.join(td, "custom-profile")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "runtime": {
                        "cdp_port": 9444,
                        "browser_profile": profile,
                        "runtime_marker": setup_wizard.RUNTIME_MARKER,
                    },
                    "routes": {
                        "owner/repo": {
                            "conversation_url": "https://chatgpt.com/c/12345678-abcd",
                            "cdp_port": 9444,
                        }
                    },
                }, handle)
            values = setup_wizard.initial_values(
                config_path=config_path, repository="owner/repo")
        self.assertEqual(values["cdp_port"], "9444")
        self.assertEqual(values["browser_profile"], os.path.abspath(profile))

    def test_reuses_only_marked_governloop_runtime(self):
        with tempfile.TemporaryDirectory() as profile:
            setup_wizard.ensure_runtime_marker(profile)
            with mock.patch.object(setup_wizard, "_cdp_reachable", return_value=True), \
                 mock.patch("subprocess.Popen") as popen:
                result = setup_wizard.ensure_browser_runtime(9233, profile)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "BROWSER_REUSED")
        popen.assert_not_called()

    def test_live_unmarked_cdp_port_fails_closed(self):
        with tempfile.TemporaryDirectory() as profile, \
             mock.patch.object(setup_wizard, "_cdp_reachable", return_value=True):
            result = setup_wizard.ensure_browser_runtime(9233, profile)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CDP_PORT_IN_USE")
        self.assertIn("rerun", result["next_required_action"])

    def test_starts_dedicated_browser_with_canonical_profile_and_port(self):
        with tempfile.TemporaryDirectory() as profile:
            popen = mock.Mock()
            with mock.patch.object(setup_wizard, "_cdp_reachable",
                                   side_effect=[False, True]), \
                 mock.patch.object(setup_wizard, "_browser_candidates",
                                   return_value=["/fake/chrome"]):
                result = setup_wizard.ensure_browser_runtime(
                    9233, profile, popen=popen, sleep=lambda _: None, timeout=1)
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "BROWSER_STARTED")
            command = popen.call_args.args[0]
            self.assertIn("--remote-debugging-port=9233", command)
            self.assertIn(f"--user-data-dir={os.path.abspath(profile)}", command)
            self.assertTrue(os.path.exists(os.path.join(profile, "GOVERNLOOP_MARKER")))
            self.assertTrue(os.path.exists(os.path.join(profile, "AGENTOPS_MARKER")))

    def test_browser_missing_returns_one_blocker_without_starting_wizard(self):
        values = {"repository": "owner/repo", "conversation_url": "",
                  "cdp_port": "9233", "browser_profile": "/tmp/profile"}
        blocker = {
            "ok": False, "status": "BROWSER_RUNTIME_BLOCKED",
            "code": "CHROME_NOT_FOUND", "detail": "missing",
            "next_required_action": "install Chrome and rerun setup",
        }
        out = io.StringIO()
        with mock.patch.object(setup_wizard, "initial_values", return_value=values), \
             mock.patch.object(setup_wizard, "ensure_browser_runtime", return_value=blocker), \
             mock.patch.object(setup_wizard, "create_setup_server") as create_server, \
             contextlib.redirect_stdout(out):
            rc = setup_wizard.run_setup(repository="owner/repo")
        self.assertEqual(rc, 2)
        create_server.assert_not_called()
        self.assertIn("SETUP_BLOCKER: CHROME_NOT_FOUND", out.getvalue())
        self.assertIn("NEXT_REQUIRED_ACTION: install Chrome and rerun setup", out.getvalue())

    def test_bind_rechecks_exact_live_conversation_before_persisting(self):
        with mock.patch.object(setup_wizard, "test_connection", return_value={
                "ok": False,
                "code": "REVIEWER_CONVERSATION_NOT_FOUND",
                "detail": "no open ChatGPT tab matches the configured conversation",
             }), mock.patch.object(setup_wizard, "_ORIGINAL_SAVE_BINDING") as save:
            with self.assertRaises(setup_wizard.SetupError) as ctx:
                setup_wizard.save_binding(
                    "/tmp/config.json", "owner/repo",
                    "https://chatgpt.com/c/12345678-abcd", 9233, "/tmp/profile")
        save.assert_not_called()
        self.assertIn("REVIEWER_BINDING_NOT_VERIFIED", str(ctx.exception))

    def test_verified_bind_delegates_to_existing_persistence_contract(self):
        expected = {"ok": True, "config_path": "/tmp/config.json"}
        with mock.patch.object(setup_wizard, "test_connection", return_value={
                "ok": True, "code": "CONNECTED",
             }), mock.patch.object(setup_wizard, "_ORIGINAL_SAVE_BINDING",
                                   return_value=expected) as save:
            result = setup_wizard.save_binding(
                "/tmp/config.json", "owner/repo",
                "https://chatgpt.com/c/12345678-abcd", 9233, "/tmp/profile")
        self.assertEqual(result, expected)
        save.assert_called_once()

    def test_wizard_copy_keeps_user_on_canonical_flow_and_runtime_read_only(self):
        values = {"repository": "owner/repo", "conversation_url": "",
                  "cdp_port": "9233", "browser_profile": "/tmp/profile"}
        page = setup_wizard._render_page(
            values, "csrf", "/tmp/config.json",
            error="CDP_UNREACHABLE: connection refused")
        self.assertIn("GovernLoop started or reused its dedicated Chrome runtime", page)
        self.assertIn("NEXT: close the dedicated GovernLoop Chrome window and rerun", page)
        self.assertIn("do not invent a different cdp port", page.lower())
        self.assertIn('name="cdp_port" inputmode="numeric" required readonly', page)
        self.assertIn('name="browser_profile" required readonly', page)


if __name__ == "__main__":
    unittest.main()
