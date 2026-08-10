import os
import sys
import tempfile
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import _compat
from governloop_runtime import setup_wizard
from governloop_runtime.__main__ import build_parser


class TestGovernLoopCompatibility(unittest.TestCase):
    def test_canonical_authority_env_maps_to_legacy_reader(self):
        with mock.patch.dict(os.environ, {
            "GOVERNLOOP_SCOPE_REPOSITORY": "owner/repo",
            "GOVERNLOOP_ALLOWED_PATHS": "src/,tests/",
        }, clear=True):
            _compat.apply_env_aliases()
            self.assertEqual(os.environ["AGENTOPS_SCOPE_REPOSITORY"], "owner/repo")
            self.assertEqual(os.environ["AGENTOPS_ALLOWED_PATHS"], "src/,tests/")

    def test_canonical_value_wins_over_legacy_value(self):
        with mock.patch.dict(os.environ, {
            "GOVERNLOOP_BASELINE_SHA": "new",
            "AGENTOPS_BASELINE_SHA": "old",
        }, clear=True):
            _compat.apply_env_aliases()
            self.assertEqual(os.environ["AGENTOPS_BASELINE_SHA"], "new")

    def test_missing_authority_stays_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            _compat.apply_env_aliases()
            self.assertNotIn("AGENTOPS_SCOPE_REPOSITORY", os.environ)
            self.assertNotIn("GOVERNLOOP_SCOPE_REPOSITORY", os.environ)

    def test_repo_first_relay_resolves_source_tree(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(_compat.relay_bin().endswith(
                "tools/neutral-relay/neutral_relay.py"))

    def test_explicit_relay_override(self):
        with mock.patch.dict(os.environ, {"GOVERNLOOP_RELAY_BIN": "~/relay.py"}, clear=True):
            self.assertEqual(_compat.relay_bin(),
                             os.path.abspath(os.path.expanduser("~/relay.py")))


class TestGovernLoopSetup(unittest.TestCase):
    def test_defaults_use_governloop_home(self):
        self.assertIn(".governloop", setup_wizard.DEFAULT_CONFIG_PATH)
        self.assertIn(".governloop", setup_wizard.DEFAULT_BROWSER_PROFILE)
        self.assertNotIn(".agentops", setup_wizard.DEFAULT_CONFIG_PATH)
        self.assertNotIn(".agentops", setup_wizard.DEFAULT_BROWSER_PROFILE)

    def test_prepare_config_uses_governloop_runtime_identity(self):
        config = setup_wizard.prepare_config(
            {}, "owner/repo", "https://chatgpt.com/c/87654321-abcd",
            9233, setup_wizard.DEFAULT_BROWSER_PROFILE)
        self.assertEqual(config["runtime"]["name"], "GovernLoop")
        self.assertEqual(config["runtime"]["runtime_marker"],
                         "governloop-runtime-v1")
        self.assertIn(".governloop", config["runtime"]["browser_profile"])
        self.assertFalse(setup_wizard.generated_config_contains_secret_fields(config))

    def test_public_render_uses_governloop_brand(self):
        values = {
            "repository": "owner/repo",
            "conversation_url": "https://chatgpt.com/c/12345678-abcd",
            "cdp_port": "9233",
            "browser_profile": setup_wizard.DEFAULT_BROWSER_PROFILE,
        }
        page = setup_wizard._render_page(
            values, "csrf", setup_wizard.DEFAULT_CONFIG_PATH)
        self.assertIn("GovernLoop", page)
        self.assertIn(".governloop", page)
        self.assertNotIn("AgentOps", page)

    def test_marker_writes_canonical_and_compatibility_files(self):
        with tempfile.TemporaryDirectory() as td:
            result = setup_wizard.ensure_runtime_marker(td)
            self.assertEqual(result, os.path.join(td, "GOVERNLOOP_MARKER"))
            for name in ("GOVERNLOOP_MARKER", "AGENTOPS_MARKER"):
                with open(os.path.join(td, name), encoding="utf-8") as handle:
                    self.assertEqual(handle.read().strip(), "governloop-runtime-v1")

    def test_prepare_config_preserves_fail_closed_port_check(self):
        existing = {
            "runtime": {"cdp_port": 9233},
            "routes": {"other/repo": {"cdp_port": 9233,
                                         "conversation_url": "https://chatgpt.com/c/12345678-abcd"}},
        }
        with self.assertRaises(setup_wizard.SetupError):
            setup_wizard.prepare_config(
                existing, "owner/repo", "https://chatgpt.com/c/87654321-abcd",
                9333, setup_wizard.DEFAULT_BROWSER_PROFILE)


class TestGovernLoopCLI(unittest.TestCase):
    def test_parser_brand_and_commands(self):
        parser = build_parser()
        self.assertEqual(parser.prog, "governloop")
        args = parser.parse_args(["setup", "--repo", "owner/repo", "--no-open"])
        self.assertEqual(args.command, "setup")
        self.assertEqual(args.repo, "owner/repo")
        self.assertTrue(args.no_open)
        self.assertIn(".governloop", args.config_file)


if __name__ == "__main__":
    unittest.main()
