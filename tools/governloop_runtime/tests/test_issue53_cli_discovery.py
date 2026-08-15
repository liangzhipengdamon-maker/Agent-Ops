import contextlib
import io
import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import cli


class TestIssue53CliDiscovery(unittest.TestCase):
    def test_instructions_is_read_only_and_does_not_enter_runtime_parser(self):
        out = io.StringIO()
        with mock.patch("governloop_runtime.cli.runtime_cli.main") as runtime_main, \
             contextlib.redirect_stdout(out):
            rc = cli.main(["instructions"])
        self.assertEqual(rc, 0)
        runtime_main.assert_not_called()
        text = out.getvalue()
        self.assertIn("governloop setup --repo <owner/repo>", text)
        self.assertIn("governloop doctor --task-id <task> --repo <owner/repo>", text)
        self.assertIn("Never infer Ready, Merge, Release, or Deploy authority", text)

    def test_top_level_help_points_agents_to_instructions_then_delegates(self):
        out = io.StringIO()
        with mock.patch("governloop_runtime.cli.runtime_cli.main", return_value=0) as runtime_main, \
             contextlib.redirect_stdout(out):
            rc = cli.main(["--help"])
        self.assertEqual(rc, 0)
        runtime_main.assert_called_once_with(["--help"])
        self.assertIn("run `governloop instructions` first", out.getvalue())

    def test_existing_commands_delegate_unchanged(self):
        argv = ["doctor", "--task-id", "AGE-X", "--repo", "owner/repo"]
        with mock.patch("governloop_runtime.cli.runtime_cli.main", return_value=2) as runtime_main:
            rc = cli.main(argv)
        self.assertEqual(rc, 2)
        runtime_main.assert_called_once_with(argv)


if __name__ == "__main__":
    unittest.main()
