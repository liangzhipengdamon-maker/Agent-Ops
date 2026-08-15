import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import cli


class TestIssue57OneCommandStart(unittest.TestCase):
    def test_repo_from_https_origin(self):
        self.assertEqual(
            cli._repo_from_origin("https://github.com/owner/repo.git"),
            "owner/repo",
        )

    def test_repo_from_scp_ssh_origin(self):
        self.assertEqual(
            cli._repo_from_origin("git@github.com:owner/repo.git"),
            "owner/repo",
        )

    def test_repo_from_ssh_url_origin(self):
        self.assertEqual(
            cli._repo_from_origin("ssh://git@github.com/owner/repo.git"),
            "owner/repo",
        )

    def test_non_github_origin_fails_closed(self):
        self.assertIsNone(cli._repo_from_origin("https://gitlab.com/owner/repo.git"))
        self.assertIsNone(cli._repo_from_origin("file:///tmp/repo"))

    def test_start_without_task_id_reports_exactly_one_missing_item(self):
        out = io.StringIO()
        with mock.patch.object(cli, "_detect_current_repo", return_value=("owner/repo", None)), \
             mock.patch.object(cli.runtime_cli, "main") as runtime_main, \
             contextlib.redirect_stdout(out):
            rc = cli.main(["start"])
        self.assertEqual(rc, 2)
        runtime_main.assert_not_called()
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["blocker"], "TASK_ID_REQUIRED")
        self.assertEqual(payload["repo"], "owner/repo")
        self.assertEqual(
            set(payload),
            {"status", "blocker", "detail", "NEXT_REQUIRED_ACTION", "repo"},
        )
        self.assertIn("--task-id <existing-task-id>", payload["NEXT_REQUIRED_ACTION"])

    def test_start_with_task_id_delegates_to_existing_doctor(self):
        with mock.patch.object(cli, "_detect_current_repo", return_value=("owner/repo", None)), \
             mock.patch.object(cli.runtime_cli, "main", return_value=0) as runtime_main:
            rc = cli.main(["start", "--task-id", "LEA-123", "--pr", "42"])
        self.assertEqual(rc, 0)
        runtime_main.assert_called_once_with([
            "doctor", "--task-id", "LEA-123", "--repo", "owner/repo", "--pr", "42",
        ])

    def test_start_without_resolvable_repo_fails_closed(self):
        out = io.StringIO()
        with mock.patch.object(
            cli, "_detect_current_repo",
            return_value=(None, "current directory is not a Git repository with remote.origin.url"),
        ), mock.patch.object(cli.runtime_cli, "main") as runtime_main, \
             contextlib.redirect_stdout(out):
            rc = cli.main(["start", "--task-id", "LEA-123"])
        self.assertEqual(rc, 2)
        runtime_main.assert_not_called()
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["blocker"], "REPOSITORY_UNRESOLVED")
        self.assertIn("target GitHub repository/worktree", payload["NEXT_REQUIRED_ACTION"])

    def test_setup_without_repo_injects_detected_repo(self):
        with mock.patch.object(cli, "_detect_current_repo", return_value=("owner/repo", None)), \
             mock.patch.object(cli.runtime_cli, "main", return_value=0) as runtime_main:
            rc = cli.main(["setup", "--no-open"])
        self.assertEqual(rc, 0)
        runtime_main.assert_called_once_with([
            "setup", "--repo", "owner/repo", "--no-open",
        ])

    def test_setup_explicit_repo_remains_unchanged(self):
        argv = ["setup", "--repo", "owner/other", "--no-open"]
        with mock.patch.object(cli, "_detect_current_repo") as detect, \
             mock.patch.object(cli.runtime_cli, "main", return_value=0) as runtime_main:
            rc = cli.main(argv)
        self.assertEqual(rc, 0)
        detect.assert_not_called()
        runtime_main.assert_called_once_with(argv)


if __name__ == "__main__":
    unittest.main()
