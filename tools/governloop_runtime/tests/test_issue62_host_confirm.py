import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import cli


class TestIssue62HostConfirm(unittest.TestCase):
    def test_without_host_confirm_delegates_unchanged(self):
        argv = ["setup-task-scope", "--task-id", "T-1"]
        with mock.patch.object(cli.runtime_cli, "main", return_value=6) as runtime_main:
            rc = cli.main(argv)
        self.assertEqual(rc, 6)
        runtime_main.assert_called_once_with(argv)

    def test_host_confirm_reuses_canonical_writer_without_real_tty(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "T-1.json"
            seen = {}

            def fake_main(argv):
                seen["argv"] = list(argv)
                seen["stdin_tty"] = sys.stdin.isatty()
                seen["stdout_tty"] = sys.stdout.isatty()
                seen["answer"] = sys.stdin.readline()
                target.write_text(json.dumps({
                    "task_id": "T-1",
                    "repository": "owner/repo",
                    "integrity_sha256": "old",
                }), encoding="utf-8")
                return 0

            argv = [
                "setup-task-scope",
                "--task-id", "T-1",
                "--repo", "owner/repo",
                "--branch", "work",
                "--baseline-sha", "a" * 40,
                "--allow-path", "/tmp/work",
                "--operation", "fix",
                "--trusted-reviewer", "reviewer",
                "--host-confirm",
            ]
            with mock.patch.object(cli.runtime_cli, "main", side_effect=fake_main), \
                 mock.patch.object(cli.runtime_cli.authority, "task_scope_path", return_value=target), \
                 mock.patch.object(cli.runtime_cli.authority, "_task_scope_integrity", return_value="new-integrity"), \
                 mock.patch.object(cli.runtime_cli.authority, "verify_task_scope", return_value={"ok": True}), \
                 contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(argv)

            self.assertEqual(rc, 0)
            self.assertNotIn("--host-confirm", seen["argv"])
            self.assertTrue(seen["stdin_tty"])
            self.assertTrue(seen["stdout_tty"])
            self.assertEqual(seen["answer"], "YES\n")
            doc = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(doc["confirmation_transport"], "host_explicit_confirm_v1")
            self.assertEqual(doc["integrity_sha256"], "new-integrity")

    def test_existing_scope_without_replace_is_not_relabelled(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "T-1.json"
            target.write_text(json.dumps({"confirmation_transport": "older"}), encoding="utf-8")
            argv = [
                "setup-task-scope", "--task-id", "T-1", "--repo", "owner/repo",
                "--host-confirm",
            ]
            with mock.patch.object(cli.runtime_cli, "main", return_value=0), \
                 mock.patch.object(cli.runtime_cli.authority, "task_scope_path", return_value=target), \
                 mock.patch.object(cli, "_record_host_confirm_provenance") as record:
                rc = cli.main(argv)
            self.assertEqual(rc, 0)
            record.assert_not_called()

    def test_replace_host_confirm_records_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "T-1.json"
            target.write_text(json.dumps({"integrity_sha256": "old"}), encoding="utf-8")

            def fake_main(argv):
                target.write_text(json.dumps({
                    "task_id": "T-1",
                    "repository": "owner/repo",
                    "integrity_sha256": "replaced",
                }), encoding="utf-8")
                return 0

            argv = [
                "setup-task-scope", "--task-id", "T-1", "--repo", "owner/repo",
                "--replace", "--host-confirm",
            ]
            with mock.patch.object(cli.runtime_cli, "main", side_effect=fake_main), \
                 mock.patch.object(cli.runtime_cli.authority, "task_scope_path", return_value=target), \
                 mock.patch.object(cli.runtime_cli.authority, "_task_scope_integrity", return_value="new"), \
                 mock.patch.object(cli.runtime_cli.authority, "verify_task_scope", return_value={"ok": True}), \
                 contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(argv)
            self.assertEqual(rc, 0)
            doc = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(doc["confirmation_transport"], "host_explicit_confirm_v1")

    def test_instructions_keep_lifecycle_separate(self):
        text = cli.AGENT_INSTRUCTIONS
        self.assertIn("--host-confirm", text)
        self.assertIn("Do not require a separate Terminal TTY", text)
        self.assertIn("never grants lifecycle permission", text)
        self.assertIn("Ready, Merge, Release, or Deploy", text)


if __name__ == "__main__":
    unittest.main()
