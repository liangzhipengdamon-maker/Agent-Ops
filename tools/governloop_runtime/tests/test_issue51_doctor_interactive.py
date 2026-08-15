import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import doctor

BASE = "0123456789abcdef0123456789abcdef01234567"
SIGNED = {
    "ok": True,
    "status": "READY",
    "authority_id": "signed-1",
    "payload": {
        "repository": "owner/repo",
        "branch": "feat/task",
        "baseline_sha": BASE,
        "allowed_paths": ["src/"],
        "allowed_operations": ["fix", "continue", "complete"],
        "trusted_reviewers": ["reviewer"],
    },
}
TASK_SCOPE = {
    "ok": True,
    "status": "INTERACTIVE_LOCAL",
    "authority_id": "interactive-local-AGE-X",
    "payload": {
        "repository": "owner/repo",
        "branch": "feat/task",
        "baseline_sha": BASE,
        "allowed_paths": ["src/"],
        "allowed_operations": ["fix", "continue", "complete"],
        "trusted_reviewers": ["reviewer"],
    },
}
MISSING = {"ok": False, "status": "BLOCKED", "detail": "authority unavailable"}


def _pass(name):
    return {"name": name, "status": "PASS", "detail": "ok"}


class TestIssue51DoctorInteractiveOnboarding(unittest.TestCase):
    def test_signed_authority_keeps_precedence(self):
        with mock.patch("governloop_runtime.doctor.authority.verify_authority", return_value=SIGNED), \
             mock.patch("governloop_runtime.doctor.authority.verify_task_scope") as task_scope:
            verified, source, _ = doctor._resolve_positive_authority("AGE-X", "owner/repo")
        self.assertIs(verified, SIGNED)
        self.assertEqual(source, "signed")
        task_scope.assert_not_called()

    def test_valid_task_scope_is_read_only_fallback(self):
        with mock.patch("governloop_runtime.doctor.authority.verify_authority", return_value=MISSING), \
             mock.patch("governloop_runtime.doctor.authority.verify_task_scope", return_value=TASK_SCOPE):
            verified, source, signed_attempt = doctor._resolve_positive_authority("AGE-X", "owner/repo")
        self.assertIs(verified, TASK_SCOPE)
        self.assertEqual(source, "interactive_local")
        self.assertIs(signed_attempt, MISSING)

    def test_task_scope_fallback_surfaces_existing_reviewer_setup_as_next_action(self):
        reviewer = {
            "name": "reviewer_binding",
            "status": "BLOCKED",
            "detail": "no reviewer route is bound for owner/repo",
            "next_action": "run `governloop setup --repo owner/repo`",
        }
        with mock.patch("governloop_runtime.doctor.authority.verify_authority", return_value=MISSING), \
             mock.patch("governloop_runtime.doctor.authority.verify_task_scope", return_value=TASK_SCOPE), \
             mock.patch("governloop_runtime.doctor._git_checks", return_value=[_pass("git_repository"), _pass("git_branch"), _pass("baseline_commit"), _pass("baseline_history"), _pass("worktree_scope")]), \
             mock.patch("governloop_runtime.doctor._github_auth_check", return_value=_pass("github_auth")), \
             mock.patch("governloop_runtime.doctor._linear_check", return_value=(_pass("linear_task"), {})), \
             mock.patch("governloop_runtime.doctor._reviewer_check", return_value=reviewer), \
             mock.patch("governloop_runtime.doctor._pr_check", return_value={"name": "pull_request", "status": "EXPECTED_GATE", "detail": "no PR"}):
            out = doctor.run_doctor("AGE-X", "owner/repo")
        self.assertEqual(out["authority_source"], "interactive_local")
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["next_required_action"]["check"], "reviewer_binding")
        self.assertEqual(out["next_required_action"]["action"], "run `governloop setup --repo owner/repo`")
        self.assertFalse(out["mutations_performed"])

    def test_no_signed_or_task_scope_keeps_existing_fail_closed_behavior(self):
        with mock.patch("governloop_runtime.doctor.authority.verify_authority", return_value=MISSING), \
             mock.patch("governloop_runtime.doctor.authority.verify_task_scope", return_value=MISSING), \
             mock.patch("governloop_runtime.doctor._git_checks", return_value=[]), \
             mock.patch("governloop_runtime.doctor._github_auth_check", return_value=_pass("github_auth")), \
             mock.patch("governloop_runtime.doctor._linear_check", return_value=(_pass("linear_task"), {})), \
             mock.patch("governloop_runtime.doctor._reviewer_check", return_value=_pass("reviewer_binding")), \
             mock.patch("governloop_runtime.doctor._pr_check", return_value={"name": "pull_request", "status": "EXPECTED_GATE", "detail": "no PR"}):
            out = doctor.run_doctor("AGE-X", "owner/repo")
        self.assertEqual(out["status"], "BLOCKED")
        self.assertIsNone(out["authority_source"])
        self.assertEqual(out["next_required_external_action"]["check"], "positive_authority")
        self.assertIn("external operator", out["next_required_external_action"]["action"])


if __name__ == "__main__":
    unittest.main()
