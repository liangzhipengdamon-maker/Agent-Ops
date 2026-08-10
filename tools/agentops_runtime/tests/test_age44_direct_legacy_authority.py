import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from agentops_runtime import runtime_loop

BASE = "0123456789abcdef0123456789abcdef01234567"
PAYLOAD = {
    "schema": "governloop-authority-v2",
    "authority_id": "external-auth-1",
    "task_id": "AGE-X",
    "repository": "owner/repo",
    "branch": "operator/branch",
    "baseline_sha": BASE,
    "allowed_paths": ["src/"],
    "allowed_operations": ["fix", "continue", "complete"],
    "trusted_reviewers": ["trusted-reviewer"],
}


class TestDirectLegacyRuntimeAuthority(unittest.TestCase):
    def _raw(self):
        return {
            "AGENTOPS_SCOPE_REPOSITORY": "owner/repo",
            "AGENTOPS_AUTHORIZED_BRANCH": "builder/branch",
            "AGENTOPS_BASELINE_SHA": BASE,
            "AGENTOPS_ALLOWED_PATHS": ".",
            "AGENTOPS_AUTHORIZED_OPERATIONS": "fix,continue,complete",
            "AGENTOPS_TRUSTED_REVIEWERS": "builder-self",
            "AGENTOPS_ALLOW_READY_MERGE_DEPLOY": "true",
        }

    def test_raw_env_may_parse_structurally_but_cannot_wake_builder(self):
        with mock.patch.dict(os.environ, self._raw(), clear=True), \
             mock.patch("governloop_runtime.authority.verify_authority",
                        return_value={"ok": False, "detail": "no external authority"}):
            structural = runtime_loop._load_scope_policy(
                "AGE-X", "owner/repo", "builder/branch", BASE, "head", "42")
            self.assertTrue(structural.binding_ok)  # diagnostic compatibility only
            out = runtime_loop.builder_handoff(
                "AGE-X", "owner/repo", "42", "head", "BUILDER_FIXING", [],
                policy=structural, observed_branch="builder/branch",
                observed_base=BASE)
        self.assertFalse(out["ok"])
        self.assertTrue(out["blocked"])
        self.assertIn("external signed operator authority", out["reason"])

    def test_executable_verified_policy_ignores_raw_env(self):
        raw = self._raw()
        raw["AGENTOPS_AUTHORIZED_BRANCH"] = "attacker/branch"
        raw["AGENTOPS_BASELINE_SHA"] = "f" * 40
        raw["AGENTOPS_AUTHORIZED_OPERATIONS"] = "merge"
        with mock.patch.dict(os.environ, raw, clear=True), \
             mock.patch("governloop_runtime.authority.verify_authority",
                        return_value={"ok": True, "payload": dict(PAYLOAD)}):
            policy = runtime_loop._verified_scope_policy(
                "AGE-X", "owner/repo", "head")
        self.assertTrue(policy.binding_ok)
        self.assertEqual(policy.repository, "owner/repo")
        self.assertEqual(policy.branch, "operator/branch")
        self.assertEqual(policy.base_sha, BASE)
        self.assertEqual(policy.allowed_paths, ("src/",))
        self.assertEqual(policy.allowed_operations,
                         ("fix", "continue", "complete"))
        self.assertFalse(policy.allowed_ready_merge_deploy)

    def test_direct_builder_handoff_reverifies_even_with_forged_policy(self):
        with mock.patch.dict(os.environ, self._raw(), clear=True), \
             mock.patch("governloop_runtime.authority.verify_authority",
                        return_value={"ok": False, "detail": "missing"}), \
             mock.patch("agentops_runtime.runtime_loop._git_origin") as origin:
            forged = runtime_loop._load_scope_policy(
                "AGE-X", "owner/repo", "builder/branch", BASE, "head", "42")
            out = runtime_loop.builder_handoff(
                "AGE-X", "owner/repo", "42", "head", "CONTINUE", [],
                policy=forged, observed_branch="builder/branch",
                observed_base=BASE)
        self.assertTrue(out["blocked"])
        origin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
