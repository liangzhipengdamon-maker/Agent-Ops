import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import doctor

MISSING = {"ok": False, "status": "BLOCKED", "detail": "authority unavailable"}


def _pass(name):
    return {"name": name, "status": "PASS", "detail": "ok"}


class TestIssue66InteractiveBootstrap(unittest.TestCase):
    def test_fresh_interactive_task_routes_to_task_scope_bootstrap(self):
        with mock.patch("governloop_runtime.doctor.authority.verify_authority", return_value=MISSING), \
             mock.patch("governloop_runtime.doctor.authority.verify_task_scope", return_value=MISSING), \
             mock.patch("governloop_runtime.doctor._git_checks", return_value=[]), \
             mock.patch("governloop_runtime.doctor._github_auth_check", return_value=_pass("github_auth")), \
             mock.patch("governloop_runtime.doctor._linear_check", return_value=(_pass("linear_task"), {})), \
             mock.patch("governloop_runtime.doctor._reviewer_check", return_value=_pass("reviewer_binding")), \
             mock.patch("governloop_runtime.doctor._pr_check", return_value={"name": "pull_request", "status": "EXPECTED_GATE", "detail": "no PR"}):
            out = doctor.run_doctor("AWG-5", "owner/repo")

        self.assertEqual(out["status"], "BLOCKED")
        self.assertIsNone(out["authority_source"])
        self.assertNotIn("next_required_external_action", out)
        self.assertEqual(out["next_required_action"]["check"], "positive_authority")
        self.assertIn("governloop setup-task-scope", out["next_required_action"]["action"])
        self.assertIn("--host-confirm", out["next_required_action"]["action"])
        self.assertIn("do not mint signed authority", out["next_required_action"]["action"])
        self.assertFalse(out["mutations_performed"])

    def test_real_signed_authority_blocker_is_still_external(self):
        check = {
            "name": "positive_authority",
            "status": "BLOCKED",
            "detail": "signed authority invalid",
            "next_action": "external operator must repair signed authority",
        }
        key, action = doctor._select_next_action([check])
        self.assertEqual(key, "next_required_external_action")
        self.assertEqual(action["check"], "positive_authority")


if __name__ == "__main__":
    unittest.main()
