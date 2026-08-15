import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import setup_wizard


class TestIssue59RunningProfileReuse(unittest.TestCase):
    def _write_active_port(self, profile, text):
        with open(os.path.join(profile, "DevToolsActivePort"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_reuses_marked_profile_actual_active_port_before_launch(self):
        with tempfile.TemporaryDirectory() as profile:
            setup_wizard.ensure_runtime_marker(profile)
            self._write_active_port(profile, "9222\n/devtools/browser/example\n")
            with mock.patch.object(
                setup_wizard, "_cdp_reachable", side_effect=lambda port: int(port) == 9222
            ) as reachable, mock.patch.object(
                setup_wizard, "_browser_candidates"
            ) as candidates, mock.patch("subprocess.Popen") as popen:
                result = setup_wizard.ensure_browser_runtime(9233, profile)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "BROWSER_REUSED")
        self.assertEqual(result["cdp_port"], 9222)
        self.assertEqual(result["runtime_source"], "DevToolsActivePort")
        reachable.assert_called_once_with(9222)
        candidates.assert_not_called()
        popen.assert_not_called()

    def test_malformed_active_port_is_not_reused(self):
        with tempfile.TemporaryDirectory() as profile:
            setup_wizard.ensure_runtime_marker(profile)
            self._write_active_port(profile, "not-a-port\n")
            with mock.patch.object(setup_wizard, "_cdp_reachable", return_value=False), \
                 mock.patch.object(setup_wizard, "_browser_candidates", return_value=[]):
                result = setup_wizard.ensure_browser_runtime(9233, profile)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHROME_NOT_FOUND")

    def test_stale_active_port_is_not_reused(self):
        with tempfile.TemporaryDirectory() as profile:
            setup_wizard.ensure_runtime_marker(profile)
            self._write_active_port(profile, "9222\n/devtools/browser/stale\n")
            with mock.patch.object(setup_wizard, "_cdp_reachable", return_value=False) as reachable, \
                 mock.patch.object(setup_wizard, "_browser_candidates", return_value=[]):
                result = setup_wizard.ensure_browser_runtime(9233, profile)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHROME_NOT_FOUND")
        self.assertEqual(reachable.call_args_list, [mock.call(9222), mock.call(9233)])

    def test_unmarked_profile_active_port_is_not_considered_reusable(self):
        with tempfile.TemporaryDirectory() as profile:
            self._write_active_port(profile, "9222\n/devtools/browser/example\n")
            with mock.patch.object(setup_wizard, "_cdp_reachable", return_value=False) as reachable, \
                 mock.patch.object(setup_wizard, "_browser_candidates", return_value=[]):
                result = setup_wizard.ensure_browser_runtime(9233, profile)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHROME_NOT_FOUND")
        reachable.assert_called_once_with(9233)

    def test_run_setup_passes_discovered_runtime_port_to_existing_wizard(self):
        values = {
            "repository": "owner/repo",
            "conversation_url": "",
            "cdp_port": "9233",
            "browser_profile": "/tmp/governloop-profile",
        }
        runtime = {
            "ok": True,
            "status": "BROWSER_REUSED",
            "cdp_port": 9222,
            "browser_profile": "/tmp/governloop-profile",
            "runtime_source": "DevToolsActivePort",
        }
        server = mock.Mock()
        server.serve_forever.side_effect = KeyboardInterrupt
        out = io.StringIO()
        with mock.patch.object(setup_wizard, "initial_values", return_value=values), \
             mock.patch.object(setup_wizard, "ensure_browser_runtime", return_value=runtime), \
             mock.patch.object(
                 setup_wizard, "create_setup_server",
                 return_value=(server, {"saved": False}, "http://127.0.0.1:9999/"),
             ) as create_server, contextlib.redirect_stdout(out):
            rc = setup_wizard.run_setup(repository="owner/repo", no_open=True)

        self.assertEqual(rc, 1)
        create_server.assert_called_once_with(
            config_path=setup_wizard.DEFAULT_CONFIG_PATH,
            repository="owner/repo",
            cdp_port=9222,
            browser_profile="/tmp/governloop-profile",
            setup_port=0,
        )
        server.server_close.assert_called_once()
        self.assertIn("BROWSER_RUNTIME: BROWSER_REUSED", out.getvalue())
        self.assertIn("BROWSER_CDP_PORT: 9222", out.getvalue())
        self.assertIn("use the setup wizard", out.getvalue())


if __name__ == "__main__":
    unittest.main()
