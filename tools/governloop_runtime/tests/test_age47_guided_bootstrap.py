import unittest
from unittest import mock

from governloop_runtime import doctor


class TestDoctorOutputHygiene(unittest.TestCase):
    def test_git_usage_dump_is_collapsed(self):
        raw = "usage: git diff [<options>]\n    --cached\n    --stat"
        self.assertEqual(
            doctor._concise_command_error(raw, "git worktree state unreadable"),
            "git worktree state unreadable",
        )

    def test_non_git_error_is_normalized(self):
        raw = "fatal: not a git repository (or any of the parent directories): .git"
        self.assertEqual(
            doctor._concise_command_error(raw, "fallback"),
            "current directory is not a git worktree",
        )

    def test_non_git_context_does_not_run_followup_git_checks(self):
        with mock.patch(
            "governloop_runtime.doctor._git_worktree_available",
            return_value=(False, "current directory is not a git worktree"),
        ), mock.patch("governloop_runtime.doctor._run") as run:
            checks = doctor._git_checks("owner/repo", {"ok": False})
        self.assertEqual(checks[0]["name"], "git_repository")
        self.assertEqual(checks[0]["status"], "BLOCKED")
        self.assertNotIn("usage:", checks[0]["detail"].lower())
        self.assertIn("clone/open", checks[0]["next_action"])
        run.assert_not_called()


class TestDoctorNextRequiredAction(unittest.TestCase):
    def test_git_repository_precedes_missing_authority(self):
        checks = [
            doctor._check(
                "positive_authority", "BLOCKED", "missing",
                next_action="external operator provisions signed authority",
            ),
            doctor._check(
                "git_repository", "BLOCKED", "not a worktree",
                next_action="clone/open target repository",
            ),
            doctor._check(
                "pull_request", "EXPECTED_GATE", "no PR",
                next_action="create Draft PR",
            ),
        ]
        key, value = doctor._select_next_action(checks)
        self.assertEqual(key, "next_required_action")
        self.assertEqual(value["check"], "git_repository")
        self.assertEqual(value["action"], "clone/open target repository")

    def test_missing_authority_is_external_after_git_is_ready(self):
        checks = [
            doctor._check("git_repository", "PASS", "origin ok"),
            doctor._check(
                "positive_authority", "BLOCKED", "missing",
                next_action="external operator provisions signed authority",
            ),
            doctor._check(
                "linear_task", "BLOCKED", "token missing",
                next_action="provide token",
            ),
        ]
        key, value = doctor._select_next_action(checks)
        self.assertEqual(key, "next_required_external_action")
        self.assertEqual(value["check"], "positive_authority")
        self.assertIn("external operator", value["action"])

    def test_earliest_blocked_gate_without_action_is_not_skipped(self):
        checks = [
            doctor._check("git_repository", "PASS", "origin ok"),
            doctor._check("positive_authority", "PASS", "signed authority ok"),
            doctor._check("git_branch", "BLOCKED", "current branch unreadable"),
            doctor._check(
                "pull_request", "EXPECTED_GATE", "no PR",
                next_action="create Draft PR",
            ),
        ]
        key, value = doctor._select_next_action(checks)
        self.assertEqual(key, "next_required_action")
        self.assertEqual(value["check"], "git_branch")
        self.assertIn("do not skip to a later gate", value["action"])
        self.assertNotIn("create Draft PR", value["action"])

    def test_blocked_pr_without_specific_action_still_has_guidance(self):
        checks = [
            doctor._check("git_repository", "PASS", "origin ok"),
            doctor._check("positive_authority", "PASS", "signed authority ok"),
            doctor._check("git_branch", "PASS", "branch ok"),
            doctor._check("baseline_commit", "PASS", "baseline ok"),
            doctor._check("baseline_history", "PASS", "history ok"),
            doctor._check("worktree_scope", "PASS", "scope ok"),
            doctor._check("github_auth", "PASS", "gh ok"),
            doctor._check("linear_task", "PASS", "linear ok"),
            doctor._check("reviewer_binding", "PASS", "reviewer ok"),
            doctor._check("pull_request", "BLOCKED", "GitHub PR response invalid"),
        ]
        key, value = doctor._select_next_action(checks)
        self.assertEqual(key, "next_required_action")
        self.assertEqual(value["check"], "pull_request")
        self.assertIn("resolve the blocked prerequisite", value["action"])

    def test_exactly_one_top_level_next_action_is_emitted(self):
        missing = {
            "ok": False,
            "detail": "OS operator control channel unavailable",
            "ignored_process_authority_fields": [],
        }
        with mock.patch(
            "governloop_runtime.doctor.authority.verify_authority",
            return_value=missing,
        ), mock.patch(
            "governloop_runtime.doctor._git_checks",
            return_value=[doctor._check("git_repository", "PASS", "origin ok")],
        ), mock.patch(
            "governloop_runtime.doctor._github_auth_check",
            return_value=doctor._check("github_auth", "PASS", "ok"),
        ), mock.patch(
            "governloop_runtime.doctor._linear_check",
            return_value=(doctor._check("linear_task", "PASS", "ok"), {}),
        ), mock.patch(
            "governloop_runtime.doctor._reviewer_check",
            return_value=doctor._check("reviewer_binding", "PASS", "ok"),
        ), mock.patch(
            "governloop_runtime.doctor._pr_check",
            return_value=doctor._check(
                "pull_request", "EXPECTED_GATE", "no PR",
                next_action="create Draft PR",
            ),
        ):
            out = doctor.run_doctor("AGE-X", "owner/repo")
        self.assertEqual(out["status"], "BLOCKED")
        self.assertIn("next_required_external_action", out)
        self.assertNotIn("next_required_action", out)
        self.assertEqual(
            out["next_required_external_action"]["check"],
            "positive_authority",
        )

    def test_execution_mode_decision_is_external(self):
        check = doctor._check(
            "linear_task", "BLOCKED", "Execution Mode is missing/ambiguous",
            next_action="Product Owner must set exactly one Execution Mode: AUTO or MANUAL",
        )
        self.assertTrue(doctor._is_external_action(check))


if __name__ == "__main__":
    unittest.main()
