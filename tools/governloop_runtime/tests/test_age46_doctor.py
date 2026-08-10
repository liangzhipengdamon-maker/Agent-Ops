import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import doctor
from governloop_runtime.__main__ import build_parser

BASE = "0123456789abcdef0123456789abcdef01234567"
AUTH = {
    "ok": True,
    "status": "READY",
    "authority_id": "auth-1",
    "payload": {
        "repository": "owner/repo",
        "branch": "feat/task",
        "baseline_sha": BASE,
        "allowed_paths": ["src/", "tests/"],
        "allowed_operations": ["fix", "continue", "complete"],
        "trusted_reviewers": ["reviewer"],
    },
}


def _pr_json(branch="feat/task", base=BASE):
    return ('{"number":42,"state":"OPEN","isDraft":true,'
            f'"headRefName":"{branch}","headRefOid":"head",'
            f'"baseRefOid":"{base}","baseRefName":"main"}}')


class TestDoctorBootstrap(unittest.TestCase):
    def test_missing_pr_is_expected_bootstrap_gate(self):
        out = doctor._pr_check("owner/repo", None, AUTH)
        self.assertEqual(out["status"], "EXPECTED_GATE")
        self.assertIn("Draft PR", out["next_action"])
        self.assertIn("no Ready/Merge authority", out["next_action"])

    def test_pr_branch_or_baseline_mismatch_blocks(self):
        with mock.patch("governloop_runtime.doctor._run",
                        return_value=(0, _pr_json(branch="wrong", base="old"), "")):
            out = doctor._pr_check("owner/repo", "42", AUTH)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertIn("head branch", out["detail"])
        self.assertIn("base", out["detail"])

    def test_matching_open_draft_pr_and_in_scope_files_pass(self):
        with mock.patch("governloop_runtime.doctor._run", side_effect=[
            (0, _pr_json(), ""), (0, "src/app.py\ntests/test_app.py", "")]):
            out = doctor._pr_check("owner/repo", "42", AUTH)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["data"]["changed_files"], ["src/app.py", "tests/test_app.py"])

    def test_pr_out_of_scope_file_blocks(self):
        with mock.patch("governloop_runtime.doctor._run", side_effect=[
            (0, _pr_json(), ""), (0, "src/app.py\nsecrets.txt", "")]):
            out = doctor._pr_check("owner/repo", "42", AUTH)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["data"]["outside_paths"], ["secrets.txt"])

    def test_unreadable_pr_file_list_fails_closed(self):
        with mock.patch("governloop_runtime.doctor._run", side_effect=[
            (0, _pr_json(), ""), (1, "", "diff unavailable")]):
            out = doctor._pr_check("owner/repo", "42", AUTH)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertIn("diff unavailable", out["detail"])

    def test_missing_authority_reports_external_operator_not_minting_command(self):
        missing = {"ok": False, "status": "BLOCKED", "missing": ["branch"],
                   "detail": "operator authority verification failed",
                   "ignored_process_authority_fields": ["GOVERNLOOP_ALLOWED_PATHS"]}
        with mock.patch("governloop_runtime.doctor.authority.verify_authority", return_value=missing), \
             mock.patch("governloop_runtime.doctor._git_checks", return_value=[]), \
             mock.patch("governloop_runtime.doctor._github_auth_check",
                        return_value={"name":"github_auth","status":"PASS","detail":"ok"}), \
             mock.patch("governloop_runtime.doctor._linear_check",
                        return_value=({"name":"linear_task","status":"PASS","detail":"ok"}, {})), \
             mock.patch("governloop_runtime.doctor._reviewer_check",
                        return_value={"name":"reviewer_binding","status":"PASS","detail":"ok"}), \
             mock.patch("governloop_runtime.doctor._pr_check",
                        return_value={"name":"pull_request","status":"EXPECTED_GATE","detail":"no PR"}):
            out = doctor.run_doctor("AGE-X", "owner/repo")
        self.assertEqual(out["status"], "BLOCKED")
        auth = out["checks"][0]
        self.assertIn("ignored raw process fields", auth["detail"])
        self.assertIn("external operator", auth["next_action"])
        self.assertNotIn("bind-authority", auth["next_action"])
        self.assertFalse(out["mutations_performed"])

    def test_only_expected_pr_gate_yields_bootstrap_required(self):
        with mock.patch("governloop_runtime.doctor.authority.verify_authority", return_value=AUTH), \
             mock.patch("governloop_runtime.doctor._git_checks",
                        return_value=[{"name":"git","status":"PASS","detail":"ok"}]), \
             mock.patch("governloop_runtime.doctor._github_auth_check",
                        return_value={"name":"github_auth","status":"PASS","detail":"ok"}), \
             mock.patch("governloop_runtime.doctor._linear_check",
                        return_value=({"name":"linear_task","status":"PASS","detail":"ok"}, {})), \
             mock.patch("governloop_runtime.doctor._reviewer_check",
                        return_value={"name":"reviewer_binding","status":"PASS","detail":"ok"}), \
             mock.patch("governloop_runtime.doctor._pr_check",
                        return_value={"name":"pull_request","status":"EXPECTED_GATE","detail":"no PR"}):
            out = doctor.run_doctor("AGE-X", "owner/repo")
        self.assertEqual(out["status"], "BOOTSTRAP_REQUIRED")
        self.assertFalse(out["mutations_performed"])

    def test_all_pass_yields_ready(self):
        with mock.patch("governloop_runtime.doctor.authority.verify_authority", return_value=AUTH), \
             mock.patch("governloop_runtime.doctor._git_checks",
                        return_value=[{"name":"git","status":"PASS","detail":"ok"}]), \
             mock.patch("governloop_runtime.doctor._github_auth_check",
                        return_value={"name":"github_auth","status":"PASS","detail":"ok"}), \
             mock.patch("governloop_runtime.doctor._linear_check",
                        return_value=({"name":"linear_task","status":"PASS","detail":"ok"}, {})), \
             mock.patch("governloop_runtime.doctor._reviewer_check",
                        return_value={"name":"reviewer_binding","status":"PASS","detail":"ok"}), \
             mock.patch("governloop_runtime.doctor._pr_check",
                        return_value={"name":"pull_request","status":"PASS","detail":"ok"}):
            out = doctor.run_doctor("AGE-X", "owner/repo", "42")
        self.assertEqual(out["status"], "READY")


class TestDoctorGitBaseline(unittest.TestCase):
    def test_exact_baseline_ancestor_passes(self):
        head = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        with mock.patch("governloop_runtime.doctor._run", side_effect=[
            (0, "git@github.com:owner/repo.git", ""),
            (0, "feat/task", ""),
            (0, "", ""),
            (0, head, ""),
            (0, "", ""),
        ]), mock.patch("governloop_runtime.doctor._worktree_scope_check",
                       return_value={"name":"worktree_scope","status":"PASS","detail":"clean"}):
            checks = doctor._git_checks("owner/repo", AUTH)
        history = next(c for c in checks if c["name"] == "baseline_history")
        self.assertEqual(history["status"], "PASS")
        self.assertEqual(history["data"]["baseline_sha"], BASE)

    def test_divergent_branch_from_existing_baseline_blocks(self):
        head = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        with mock.patch("governloop_runtime.doctor._run", side_effect=[
            (0, "git@github.com:owner/repo.git", ""),
            (0, "feat/task", ""),
            (0, "", ""),
            (0, head, ""),
            (1, "", ""),
        ]), mock.patch("governloop_runtime.doctor._worktree_scope_check",
                       return_value={"name":"worktree_scope","status":"PASS","detail":"clean"}):
            checks = doctor._git_checks("owner/repo", AUTH)
        baseline = next(c for c in checks if c["name"] == "baseline_commit")
        history = next(c for c in checks if c["name"] == "baseline_history")
        self.assertEqual(baseline["status"], "PASS")
        self.assertEqual(history["status"], "BLOCKED")
        self.assertIn("does not descend", history["detail"])

    def test_unreadable_ancestry_fails_closed(self):
        head = "cccccccccccccccccccccccccccccccccccccccc"
        with mock.patch("governloop_runtime.doctor._run", side_effect=[
            (0, "git@github.com:owner/repo.git", ""),
            (0, "feat/task", ""),
            (0, "", ""),
            (0, head, ""),
            (128, "", "fatal: shallow history"),
        ]), mock.patch("governloop_runtime.doctor._worktree_scope_check",
                       return_value={"name":"worktree_scope","status":"PASS","detail":"clean"}):
            checks = doctor._git_checks("owner/repo", AUTH)
        history = next(c for c in checks if c["name"] == "baseline_history")
        self.assertEqual(history["status"], "BLOCKED")
        self.assertIn("shallow history", history["detail"])


class TestDoctorWorktreeScope(unittest.TestCase):
    def test_clean_worktree_passes(self):
        with mock.patch("governloop_runtime.doctor._changed_worktree_paths", return_value=([], [])):
            out = doctor._worktree_scope_check(AUTH)
        self.assertEqual(out["status"], "PASS")

    def test_in_scope_dirty_paths_pass(self):
        with mock.patch("governloop_runtime.doctor._changed_worktree_paths",
                        return_value=(["src/app.py", "tests/test_app.py"], [])):
            out = doctor._worktree_scope_check(AUTH)
        self.assertEqual(out["status"], "PASS")

    def test_unrelated_dirty_path_blocks(self):
        with mock.patch("governloop_runtime.doctor._changed_worktree_paths",
                        return_value=(["src/app.py", "notes/private.txt"], [])):
            out = doctor._worktree_scope_check(AUTH)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["data"]["outside_paths"], ["notes/private.txt"])

    def test_unreadable_worktree_state_fails_closed(self):
        with mock.patch("governloop_runtime.doctor._changed_worktree_paths",
                        return_value=([], ["git diff failed"])):
            out = doctor._worktree_scope_check(AUTH)
        self.assertEqual(out["status"], "BLOCKED")


class TestDoctorCLI(unittest.TestCase):
    def test_doctor_pr_is_optional(self):
        args = build_parser().parse_args(["doctor", "--task-id", "AGE-X", "--repo", "owner/repo"])
        self.assertEqual(args.command, "doctor")
        self.assertIsNone(args.pr)

    def test_doctor_can_disable_live_reviewer_probe(self):
        args = build_parser().parse_args(["doctor", "--task-id", "AGE-X", "--repo", "owner/repo",
                                          "--no-reviewer-probe"])
        self.assertTrue(args.no_reviewer_probe)


if __name__ == "__main__":
    unittest.main()
