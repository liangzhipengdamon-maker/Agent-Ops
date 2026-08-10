import unittest
import os
import sys
import tempfile
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from agentops_runtime.scope_firewall import (
    ScopePolicy, ActionScope, WorktreeState, evaluate_scope,
    evaluate_builder_wake, LIFECYCLE_ACTIONS, _is_path_allowed,
    _is_protected,
)
from agentops_runtime.runtime_loop import (
    builder_handoff, _load_scope_policy, decide,
)


def make_policy(**kw):
    base = dict(
        task_id="AGE-6",
        repository="liangzhipengdamon-maker/Agent-Ops",
        branch="liangzhipengdamon/age-6-age-6-deterministic-scope-action-firewall",
        base_sha="f93b1859bb63a2eb342789bf6bca3269b4f2c7de",
        head_sha="abc123",
        allowed_paths=("tools/agentops_runtime/", "scripts/", "profiles/",
                       "docs/", "tests/"),
        allowed_operations=("fix", "continue", "complete"),
        protected_repositories=(
            "liangzhipengdamon-maker/LearnMind-English",
            "liangzhipengdamon-maker/AI-Investment-Lab",
        ),
    )
    base.update(kw)
    return ScopePolicy(**base)


def make_action(**kw):
    base = dict(
        task_id="AGE-6",
        repository="liangzhipengdamon-maker/Agent-Ops",
        branch="liangzhipengdamon/age-6-age-6-deterministic-scope-action-firewall",
        base_sha="f93b1859bb63a2eb342789bf6bca3269b4f2c7de",
        head_sha="abc123",
        target_paths=("tools/agentops_runtime/scope_firewall.py",),
        operation="fix",
    )
    base.update(kw)
    return ActionScope(**base)


class TestPathRules(unittest.TestCase):
    def test_traversal_rejected(self):
        self.assertFalse(_is_path_allowed("../outside", ["tools/"]))

    def test_absolute_rejected(self):
        self.assertFalse(_is_path_allowed("/etc/passwd", ["tools/"]))

    def test_exact_allowed(self):
        self.assertTrue(_is_path_allowed("tools/a.py", ["tools/"]))

    def test_prefix_allowed(self):
        self.assertTrue(_is_path_allowed("tools/x/y/z.py", ["tools/"]))

    def test_outside_rejected(self):
        self.assertFalse(_is_path_allowed("other/x.py", ["tools/"]))

    def test_wildcard_not_authorized(self):
        # '*' is treated literally, so "tools/*" does not authorize tools/a.py
        self.assertFalse(_is_path_allowed("tools/a.py", ["tools/*"]))

    def test_protected_path_rejected(self):
        self.assertTrue(_is_protected(
            "liangzhipengdamon-maker/LearnMind-English/src/a.py",
            ["liangzhipengdamon-maker/LearnMind-English"]))


class TestEvaluateScope(unittest.TestCase):
    def test_positive_correctly_bound_passes(self):
        p = make_policy()
        a = make_action()
        r = evaluate_scope(p, a, worktree=WorktreeState(
            current_branch=p.branch, has_uncommitted_changes=False))
        self.assertTrue(r["ok"])
        self.assertFalse(r["blocked"])
        self.assertTrue(all(r["checks"].values()))

    def test_repository_mismatch_fails(self):
        r = evaluate_scope(make_policy(),
                           make_action(repository="other/repo"))
        self.assertFalse(r["ok"])

    def test_protected_repository_denied(self):
        # AgentOps task targeting LearnMind-English without a separately
        # scoped policy -> denied.
        r = evaluate_scope(
            make_policy(),
            make_action(repository="liangzhipengdamon-maker/LearnMind-English"))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["not_protected_repository"])

    def test_ai_investment_lab_denied(self):
        r = evaluate_scope(
            make_policy(),
            make_action(repository="liangzhipengdamon-maker/AI-Investment-Lab"))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["not_protected_repository"])

    def test_branch_mismatch_fails(self):
        r = evaluate_scope(make_policy(),
                           make_action(branch="main"))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["branch_exact"])

    def test_base_sha_mismatch_fails(self):
        r = evaluate_scope(make_policy(),
                           make_action(base_sha="stale-sha"))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["base_sha_exact"])

    def test_head_sha_mismatch_fails_when_pinned(self):
        r = evaluate_scope(make_policy(head_sha="expected"),
                           make_action(head_sha="drifted"))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["head_exact"])

    def test_path_outside_fails(self):
        r = evaluate_scope(make_policy(),
                           make_action(target_paths=("outside/x.py",)))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["paths_allowed"])

    def test_path_traversal_fails(self):
        r = evaluate_scope(make_policy(),
                           make_action(target_paths=("../evil.py",)))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["paths_allowed"])

    def test_absolute_path_fails(self):
        r = evaluate_scope(make_policy(),
                           make_action(target_paths=("/tmp/x.py",)))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["paths_allowed"])

    def test_protected_path_fails(self):
        r = evaluate_scope(make_policy(), make_action(
            target_paths=("LearnMind-English/src/a.py",)))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["paths_allowed"])

    def test_disallowed_operation_fails(self):
        r = evaluate_scope(make_policy(),
                           make_action(operation="delete"))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["operation_allowed"])

    def test_ready_merge_deploy_never_implied(self):
        for op in LIFECYCLE_ACTIONS:
            with self.subTest(op=op):
                r = evaluate_scope(
                    make_policy(allowed_ready_merge_deploy=False),
                    make_action(operation=op))
                self.assertFalse(r["ok"])
                self.assertFalse(r["checks"]["no_implied_ready_merge_deploy"])

    def test_ready_merge_deploy_allowed_only_with_explicit_auth(self):
        p = make_policy(allowed_ready_merge_deploy=True,
                        allowed_operations=("merge",))
        r = evaluate_scope(p, make_action(operation="merge"))
        self.assertTrue(r["ok"])

    def test_dirty_worktree_unrelated_change_fails(self):
        r = evaluate_scope(
            make_policy(),
            make_action(),
            worktree=WorktreeState(
                current_branch="liangzhipengdamon/age-6-age-6-deterministic-scope-action-firewall",
                has_uncommitted_changes=True,
                changed_paths=("README.md",)))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["clean_worktree"])

    def test_dirty_worktree_in_scope_change_passes(self):
        r = evaluate_scope(
            make_policy(),
            make_action(),
            worktree=WorktreeState(
                current_branch="liangzhipengdamon/age-6-age-6-deterministic-scope-action-firewall",
                has_uncommitted_changes=True,
                changed_paths=("tools/agentops_runtime/scope_firewall.py",)))
        self.assertTrue(r["ok"])

    def test_worktree_branch_mismatch_fails(self):
        r = evaluate_scope(
            make_policy(),
            make_action(),
            worktree=WorktreeState(current_branch="main",
                                   has_uncommitted_changes=False))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["clean_worktree"])

    def test_task_scope_cannot_switch(self):
        r = evaluate_scope(make_policy(), make_action(task_id="AGE-99"))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["task_scope_locked"])

    def test_empty_paths_fail_closed(self):
        r = evaluate_scope(make_policy(), make_action(target_paths=()))
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["paths_allowed"])

    def test_authoritative_changed_file_in_scope_passes(self):
        p = make_policy(authoritative_changed_files=(
            "tools/agentops_runtime/scope_firewall.py",
            "tools/agentops_runtime/runtime_loop.py"))
        r = evaluate_builder_wake(p, "AGE-6",
                                  "liangzhipengdamon-maker/Agent-Ops",
                                  "liangzhipengdamon/age-6-age-6-deterministic-scope-action-firewall",
                                  "f93b1859bb63a2eb342789bf6bca3269b4f2c7de",
                                  "abc123")
        self.assertTrue(r["ok"])
        self.assertTrue(r["checks"]["changed_files_in_scope"])

    def test_authoritative_changed_file_out_of_scope_fails(self):
        # P0-2: a committed out-of-scope file in the authoritative PR diff
        # blocks the wake even when the worktree is clean.
        p = make_policy(authoritative_changed_files=(
            "LearnMind-English/src/a.py",))
        r = evaluate_builder_wake(p, "AGE-6",
                                  "liangzhipengdamon-maker/Agent-Ops",
                                  "liangzhipengdamon/age-6-age-6-deterministic-scope-action-firewall",
                                  "f93b1859bb63a2eb342789bf6bca3269b4f2c7de",
                                  "abc123")
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["changed_files_in_scope"])

    def test_authoritative_changed_file_protected_path_fails(self):
        p = make_policy(authoritative_changed_files=(
            "liangzhipengdamon-maker/AI-Investment-Lab/config.yaml",))
        r = evaluate_builder_wake(p, "AGE-6",
                                  "liangzhipengdamon-maker/Agent-Ops",
                                  "liangzhipengdamon/age-6-age-6-deterministic-scope-action-firewall",
                                  "f93b1859bb63a2eb342789bf6bca3269b4f2c7de",
                                  "abc123")
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["changed_files_in_scope"])


class TestBuilderHandoffFirewall(unittest.TestCase):
    def test_no_policy_fails_closed_no_wake(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td):
            r = builder_handoff("AGE-6", "o/r", "1", "h", "BUILDER_FIXING",
                                ["findings"])
            files = os.listdir(td)
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])
        self.assertNotIn("findings.md", files)
        self.assertNotIn("status.json", files)

    def test_policy_mismatch_blocks_wake(self):
        p = make_policy()
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td):
            r = builder_handoff("AGE-6",
                                "liangzhipengdamon-maker/LearnMind-English",
                                "1", "h", "BUILDER_FIXING", ["x"],
                                policy=p)
            files = os.listdir(td)
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])
        self.assertNotIn("findings.md", files)
        self.assertNotIn("status.json", files)

    def test_policy_match_writes_wake(self):
        p = make_policy()
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td), \
             mock.patch("agentops_runtime.runtime_loop.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="")) as m:
            r = builder_handoff("AGE-6",
                                "liangzhipengdamon-maker/Agent-Ops",
                                "1", "abc123", "BUILDER_FIXING", ["x"],
                                policy=p,
                                observed_branch=p.branch,
                                observed_base=p.base_sha)
            files = os.listdir(td)
        self.assertTrue(r["ok"])
        self.assertFalse(r.get("blocked"))
        self.assertIn("status.json", files)
        self.assertIn("findings.md", files)

    def test_merge_operation_never_emitted_by_runtime_phase(self):
        # The runtime only ever hands off fix/continue/complete phases; verify
        # no runtime phase maps to a lifecycle action.
        for phase in ("BUILDER_FIXING", "CONTINUE", "COMPLETE"):
            with self.subTest(phase=phase):
                self.assertNotIn(phase.lower().replace("builder_", ""),
                                 LIFECYCLE_ACTIONS)


class TestLoadScopePolicy(unittest.TestCase):
    def test_default_policy_binds_context(self):
        with tempfile.TemporaryDirectory() as td:
            prof = os.path.join(td, "agentops.json")
            with open(prof, "w") as f:
                f.write('{"github": {"repository": "liangzhipengdamon-maker/Agent-Ops",'
                        ' "canonical_branch": "main"},'
                        ' "scope_firewall": {"authorized_branch": "feature/x",'
                        ' "baseline_sha": "base1"}}')
            p = _load_scope_policy(
                "AGE-6", "liangzhipengdamon-maker/Agent-Ops",
                "feature/x", "base1", "head1", "7", profile_path=prof)
        self.assertEqual(p.repository, "liangzhipengdamon-maker/Agent-Ops")
        self.assertEqual(p.branch, "feature/x")
        self.assertEqual(p.base_sha, "base1")
        self.assertEqual(p.head_sha, "head1")
        self.assertIn("liangzhipengdamon-maker/LearnMind-English",
                      p.protected_repositories)
        self.assertFalse(p.allowed_ready_merge_deploy)
        self.assertTrue(p.binding_ok)

    def test_profile_branch_base_not_self_derived(self):
        # P0-1: expected branch/base come from the profile, NOT from the
        # observed PR metadata. A drifted PR branch/base fails closed.
        with tempfile.TemporaryDirectory() as td:
            prof = os.path.join(td, "agentops.json")
            with open(prof, "w") as f:
                f.write('{"github": {"repository": "liangzhipengdamon-maker/Agent-Ops",'
                        ' "canonical_branch": "main"},'
                        ' "scope_firewall": {"authorized_branch": "feature/x",'
                        ' "baseline_sha": "base1"}}')
            p = _load_scope_policy(
                "AGE-6", "liangzhipengdamon-maker/Agent-Ops",
                "feature/y", "base2", "head1", "7", profile_path=prof)
        self.assertEqual(p.branch, "feature/x")   # profile, not observed
        self.assertEqual(p.base_sha, "base1")
        # Drift detected when evaluated with observed branch/base.
        a = ActionScope(task_id="AGE-6",
                        repository="liangzhipengdamon-maker/Agent-Ops",
                        branch="feature/y", base_sha="base2",
                        target_paths=("x.py",))
        r = evaluate_scope(p, a)
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["branch_exact"])
        self.assertFalse(r["checks"]["base_sha_exact"])

    def test_profile_repo_mismatch_binding_fails_closed(self):
        # P0-1: invocation repo differs from the independent profile's
        # canonical repository -> policy binding_ok=False.
        with tempfile.TemporaryDirectory() as td:
            prof = os.path.join(td, "agentops.json")
            with open(prof, "w") as f:
                f.write('{"github": {"repository": "liangzhipengdamon-maker/Agent-Ops",'
                        ' "canonical_branch": "main"}}')
            p = _load_scope_policy(
                "AGE-6", "other/repo", "feature/x", "base1", "head1", "7",
                profile_path=prof)
        self.assertFalse(p.binding_ok)

    def test_default_allowed_paths_has_no_implicit_dot(self):
        # P0-2: production default allowed paths must NOT include '.' (no
        # implicit whole-repo bypass). Explicit paths only.
        with tempfile.TemporaryDirectory() as td:
            prof = os.path.join(td, "agentops.json")
            with open(prof, "w") as f:
                f.write('{"github": {"repository": "liangzhipengdamon-maker/Agent-Ops"}}')
            p = _load_scope_policy(
                "AGE-6", "liangzhipengdamon-maker/Agent-Ops",
                "feature/x", "base1", "head1", "7", profile_path=prof)
        self.assertNotIn(".", p.allowed_paths)
        self.assertIn("tools/agentops_runtime/", p.allowed_paths)

    def test_binding_ok_false_blocks_evaluate(self):
        p = ScopePolicy(task_id="AGE-6",
                        repository="liangzhipengdamon-maker/Agent-Ops",
                        branch="b", base_sha="s", binding_ok=False)
        a = ActionScope(task_id="AGE-6",
                        repository="liangzhipengdamon-maker/Agent-Ops",
                        branch="b", base_sha="s", target_paths=("x.py",))
        r = evaluate_scope(p, a)
        self.assertFalse(r["ok"])
        self.assertFalse(r["checks"]["binding_ok"])


class TestDecideFirewallIntegration(unittest.TestCase):
    """decide() with the REAL builder_handoff: a correctly bound scope emits a
    Builder wake; a cross-repo target fails closed with no executable wake."""

    def _open_pr(self):
        return mock.patch("agentops_runtime.runtime_loop._pr_state",
                          return_value={"state": "OPEN"})

    def _base_pr(self, repo="liangzhipengdamon-maker/Agent-Ops"):
        return mock.patch(
            "agentops_runtime.runtime_loop._pr_json_full",
            return_value={"reviews": [],
                          "headRefOid": "abc123",
                          "baseRefOid": "f93b1859bb63a2eb342789bf6bca3269b4f2c7de",
                          "headRefName":
                              "liangzhipengdamon/age-6-age-6-deterministic-scope-action-firewall"})

    def _bridge(self):
        return mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                          return_value=tempfile.mkdtemp())

    def test_cross_repo_target_blocked_no_wake(self):
        # An AgentOps decide() handed a protected/cross repo must not emit a
        # Builder wake (firewall fails closed).
        with tempfile.TemporaryDirectory() as td, \
             self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td), \
             self._base_pr(repo="liangzhipengdamon-maker/Agent-Ops"), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=__import__(
                            "agentops_runtime.task_intake", fromlist=["TaskSpec"]
                        ).TaskSpec("AGE-6", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=__import__(
                            "agentops_runtime.review_intake", fromlist=["ReviewOutcome"]
                        ).ReviewOutcome("COMMENTED", "CHANGES_REQUESTED",
                                        "liangzhipengdamon-maker/LearnMind-English",
                                        1, "abc123", ["fix"])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc123"), \
             mock.patch("agentops_runtime.runtime_loop.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="")), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-6",
                         "liangzhipengdamon-maker/LearnMind-English", "1")
            files = os.listdir(td)
        # P0-3: firewall rejection -> phase BLOCKED (AGE-6 fail-closed), never
        # FIX with an executable-looking wake.
        self.assertEqual(out["phase"], "BLOCKED")
        self.assertEqual(out["review_decision"], "SCOPE_BLOCKED")
        self.assertFalse(out["builder"]["ok"])
        self.assertTrue(out["builder"]["blocked"])
        self.assertNotIn("status.json", files)
        self.assertNotIn("findings.md", files)

    def test_bound_target_emits_wake(self):
        # A correctly bound AgentOps target emits the Builder wake.
        with tempfile.TemporaryDirectory() as td, \
             self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td), \
             self._base_pr(), \
             mock.patch("agentops_runtime.runtime_loop._pr_changed_files",
                        return_value=[
                            "tools/agentops_runtime/scope_firewall.py"]), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=__import__(
                            "agentops_runtime.task_intake", fromlist=["TaskSpec"]
                        ).TaskSpec("AGE-6", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=__import__(
                            "agentops_runtime.review_intake", fromlist=["ReviewOutcome"]
                        ).ReviewOutcome("COMMENTED", "CHANGES_REQUESTED",
                                        "liangzhipengdamon-maker/Agent-Ops",
                                        1, "abc123", ["fix"])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc123"), \
             mock.patch("agentops_runtime.runtime_loop.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="")), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-6",
                         "liangzhipengdamon-maker/Agent-Ops", "1")
            files = os.listdir(td)
        self.assertEqual(out["phase"], "FIX")
        self.assertTrue(out["builder"]["ok"])
        self.assertIn("status.json", files)
        self.assertIn("findings.md", files)


if __name__ == "__main__":
    unittest.main()
