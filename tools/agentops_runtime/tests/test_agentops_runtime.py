import unittest
import os
import sys
import json
import tempfile
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

import agentops_runtime.__main__ as cli
from agentops_runtime import linear_adapter, review_intake
from agentops_runtime.task_intake import parse_mode, extract_checkpoint, spec_from_linear, TaskSpec
from agentops_runtime.review_intake import review_from_github, ReviewOutcome
from agentops_runtime.runtime_loop import RuntimeLoop, LoopState
from agentops_runtime.delivery import build_completion_report, DeliveryResult


AUTO_DESC = """# Task

Execution Mode: AUTO

Acceptance criteria:
- The AUTO sandbox task is picked up from Linear and executed
- A review NOT_PASS automatically returns to the Builder
- PASS continues in scope
"""

MANUAL_DESC = """# Task

Execution Mode: MANUAL
checkpoint: final approval

Acceptance criteria:
- Pauses only at the named checkpoint
- Resumes after PO decision
"""

BOTH_WORDS_DESC = """# Task

Execution Mode: AUTO

The description also discusses MANUAL mode for comparison.
"""


class TestTaskIntake(unittest.TestCase):
    def test_parse_mode_auto(self):
        self.assertEqual(parse_mode(AUTO_DESC), "AUTO")

    def test_parse_mode_manual(self):
        self.assertEqual(parse_mode(MANUAL_DESC), "MANUAL")

    def test_parse_mode_ambiguous_returns_empty(self):
        # Both AUTO and MANUAL present -> ambiguous, no default.
        self.assertEqual(parse_mode("AUTO and MANUAL both"), "")

    def test_explicit_execution_mode_field_wins(self):
        # Even though the text mentions MANUAL, the explicit field says AUTO.
        self.assertEqual(parse_mode(BOTH_WORDS_DESC), "AUTO")

    def test_parse_mode_missing_returns_empty(self):
        self.assertEqual(parse_mode("no mode"), "")

    def test_extract_checkpoint(self):
        self.assertEqual(extract_checkpoint(MANUAL_DESC), "final approval")

    def test_spec_from_linear_auto(self):
        with mock.patch.object(linear_adapter, "read_linear_issue",
                               return_value={"identifier": "AGE-X",
                                             "title": "t",
                                             "description": AUTO_DESC,
                                             "state_name": "In Progress",
                                             "state_type": "started"}):
            spec = spec_from_linear("AGE-X")
            self.assertEqual(spec.mode, "AUTO")
            self.assertGreaterEqual(len(spec.acceptance_criteria), 1)

    def test_spec_from_linear_manual_checkpoint(self):
        with mock.patch.object(linear_adapter, "read_linear_issue",
                               return_value={"identifier": "AGE-X",
                                             "title": "t",
                                             "description": MANUAL_DESC,
                                             "state_name": "In Progress",
                                             "state_type": "started"}):
            spec = spec_from_linear("AGE-X")
            self.assertEqual(spec.mode, "MANUAL")
            self.assertEqual(spec.checkpoint, "final approval")


class TestReviewIntake(unittest.TestCase):
    HEAD = "abc123def"

    def _pr(self, rd=None, mergeable="MERGEABLE", head=None, reviews=None):
        return {"reviewDecision": rd, "mergeable": mergeable,
                "headRefOid": head or self.HEAD, "reviews": reviews or []}

    def test_approved_pass(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(rd="APPROVED"))
        self.assertEqual(r.decision, "PASS")
        self.assertFalse(r.fail_closed)

    def test_changes_requested(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd="CHANGES_REQUESTED",
            reviews=[{"state": "CHANGES_REQUESTED",
                      "body": "fix the P0"}]))
        self.assertEqual(r.decision, "CHANGES_REQUESTED")
        self.assertEqual(len(r.findings), 1)

    def test_comment_not_pass(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": "Independent Review - NOT PASS: fix x"}]))
        self.assertEqual(r.decision, "NOT_PASS")

    def test_formal_comment_pass(self):
        # P0-3: same-owner review path uses formal COMMENTED AGENTOPS_REVIEW
        # verdict for PASS too (not just GitHub APPROVED).
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": f"AGENTOPS_REVIEW: PASS\nHEAD: {self.HEAD}"}]))
        self.assertEqual(r.decision, "PASS")

    def test_formal_comment_changes_requested(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": f"AGENTOPS_REVIEW: CHANGES_REQUESTED\nHEAD: {self.HEAD}\nfix P0"}]))
        self.assertEqual(r.decision, "CHANGES_REQUESTED")

    def test_formal_review_for_stale_head_ignored(self):
        # P0-2: a formal review naming a DIFFERENT HEAD must be INCOMPLETE,
        # never applied to the current HEAD.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": "AGENTOPS_REVIEW: PASS\nHEAD: oldhead123"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_head_mismatch_fail_closed(self):
        r = review_from_github("o/r", 1, self.HEAD,
                               self._pr(rd="APPROVED", head="other"))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_conflict_fail_closed(self):
        r = review_from_github("o/r", 1, self.HEAD,
                               self._pr(rd="APPROVED", mergeable="CONFLICTING"))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_incomplete_fail_closed(self):
        r = review_from_github("o/r", 1, self.HEAD,
                               self._pr(rd=None, reviews=[{"state": "COMMENTED", "body": "ok"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)


class TestRuntimeLoop(unittest.TestCase):
    def _loop(self, td):
        return RuntimeLoop("AGE-X", "o/r", "7", td)

    def _open_pr(self):
        return mock.patch("agentops_runtime.runtime_loop._pr_state",
                          return_value={"state": "OPEN"})

    def test_step_review_fix(self):
        with tempfile.TemporaryDirectory() as td:
            loop = self._loop(td)
            with self._open_pr(), \
                 mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                            return_value=ReviewOutcome(
                                "CHANGES_REQUESTED", "CHANGES_REQUESTED",
                                "o/r", 7, "abc", ["fix"])), \
                 mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                            return_value="abc"):
                st = loop.step("AUTO", None, acceptance_ok=False)
            self.assertEqual(st.phase, "FIX")
            self.assertEqual(st.review_decision, "CHANGES_REQUESTED")

    def test_step_pass_continue(self):
        with tempfile.TemporaryDirectory() as td:
            loop = self._loop(td)
            with self._open_pr(), \
                 mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                            return_value=ReviewOutcome(
                                "APPROVED", "PASS", "o/r", 7, "abc", [])), \
                 mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                            return_value="abc"):
                st = loop.step("AUTO", None, acceptance_ok=False)
            self.assertEqual(st.phase, "PASSED")

    def test_step_pass_acceptance_complete(self):
        with tempfile.TemporaryDirectory() as td:
            loop = self._loop(td)
            with self._open_pr(), \
                 mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                            return_value=ReviewOutcome(
                                "APPROVED", "PASS", "o/r", 7, "abc", [])), \
                 mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                            return_value="abc"):
                st = loop.step("AUTO", None, acceptance_ok=True)
            self.assertEqual(st.phase, "COMPLETE")

    def test_manual_pause_at_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            loop = self._loop(td)
            with self._open_pr(), \
                 mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                            return_value=ReviewOutcome(
                                "APPROVED", "PASS", "o/r", 7, "abc", [])), \
                 mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                            return_value="abc"):
                st = loop.step("MANUAL", "final approval", acceptance_ok=False)
            self.assertEqual(st.phase, "WAITING_PO_AUTH")

    def test_closed_pr_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            loop = self._loop(td)
            with mock.patch("agentops_runtime.runtime_loop._pr_state",
                            return_value={"state": "CLOSED"}):
                st = loop.step("AUTO", None, acceptance_ok=False)
            self.assertEqual(st.phase, "TERMINAL")

    def test_unreadable_remote_is_blocked_not_terminal(self):
        # P0-6: unreadable remote state is BLOCKED/retryable, never accepted
        # terminal closure.
        with tempfile.TemporaryDirectory() as td:
            loop = self._loop(td)
            with mock.patch("agentops_runtime.runtime_loop._pr_state",
                            return_value=None):
                st = loop.step("AUTO", None, acceptance_ok=False)
            self.assertEqual(st.phase, "BLOCKED")

    def test_fix_emits_builder_wake(self):
        # P0-1: CHANGES_REQUESTED -> FIX -> Builder wake emitted (real
        # Builder handoff, no PO copy/paste).
        with tempfile.TemporaryDirectory() as td:
            loop = self._loop(td)
            with self._open_pr(), \
                 mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                            return_value=ReviewOutcome(
                                "CHANGES_REQUESTED", "CHANGES_REQUESTED",
                                "o/r", 7, "abc", ["fix P0"])), \
                 mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                            return_value="abc"):
                st = loop.step("AUTO", None, acceptance_ok=False)
            self.assertEqual(st.phase, "FIX")
            wake_path = os.path.join(td, "wake_AGE-X.json")
            self.assertTrue(os.path.exists(wake_path))
            with open(wake_path) as f:
                wake = json.load(f)
            self.assertEqual(wake["action"], "apply_fix_and_push_new_head")
            self.assertEqual(wake["findings"], ["fix P0"])

    def test_manual_pauses_only_on_current_head_pass(self):
        # P0-4: MANUAL pauses only on a current-HEAD PASS, not on stale or
        # missing reviews.
        with tempfile.TemporaryDirectory() as td:
            loop = self._loop(td)
            # stale review for a different head -> INCOMPLETE -> REVIEW, not
            # WAITING_PO_AUTH
            with self._open_pr(), \
                 mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                            return_value=ReviewOutcome(
                                "INCOMPLETE", "INCOMPLETE",
                                "o/r", 7, "abc", [], fail_closed=True)), \
                 mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                            return_value="abc"):
                st = loop.step("MANUAL", "final approval", acceptance_ok=False)
            self.assertEqual(st.phase, "REVIEW")
            # current-HEAD PASS -> checkpoint reached -> WAITING_PO_AUTH
            with self._open_pr(), \
                 mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                            return_value=ReviewOutcome(
                                "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
                 mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                            return_value="abc"):
                st2 = loop.step("MANUAL", "final approval", acceptance_ok=False)
            self.assertEqual(st2.phase, "WAITING_PO_AUTH")


class TestCLIEntrypoint(unittest.TestCase):
    """Tests the production entrypoint (run-auto / run-manual / report)."""

    def test_run_auto_mode_missing_surfaces_decision(self):
        with mock.patch("agentops_runtime.__main__.spec_from_linear",
                        return_value=TaskSpec(
                            "AGE-X", mode="", checkpoint=None,
                            acceptance_criteria=[], description="no mode",
                            state_name="", state_type="")):
            rc = cli.main(["run-auto", "--task-id", "AGE-X",
                           "--repo", "o/r", "--pr", "7",
                           "--state-dir", "/tmp/x"])
        self.assertEqual(rc, 2)

    def test_run_auto_task_is_manual(self):
        with mock.patch("agentops_runtime.__main__.spec_from_linear",
                        return_value=TaskSpec(
                            "AGE-X", mode="MANUAL", checkpoint="final",
                            acceptance_criteria=[], description="MANUAL",
                            state_name="", state_type="")):
            rc = cli.main(["run-auto", "--task-id", "AGE-X",
                           "--repo", "o/r", "--pr", "7",
                           "--state-dir", "/tmp/x"])
        self.assertEqual(rc, 2)

    def test_run_manual_missing_checkpoint(self):
        with mock.patch("agentops_runtime.__main__.spec_from_linear",
                        return_value=TaskSpec(
                            "AGE-X", mode="MANUAL", checkpoint=None,
                            acceptance_criteria=[], description="MANUAL",
                            state_name="", state_type="")):
            rc = cli.main(["run-manual", "--task-id", "AGE-X",
                           "--repo", "o/r", "--pr", "7",
                           "--state-dir", "/tmp/x"])
        self.assertEqual(rc, 2)

    def test_report_command_sends_and_confirms(self):
        with tempfile.TemporaryDirectory() as td:
            sec = os.path.join(td, "s.json")
            with open(sec, "w") as f:
                json.dump({"Task": "x"}, f)
            with mock.patch("agentops_runtime.__main__._head",
                            return_value="abcd1234"), \
                 mock.patch("agentops_runtime.__main__.NeutralRelayNotifier") as MN, \
                 mock.patch("agentops_runtime.__main__.GptWebContextReadback") as MR:
                n = MN.return_value
                n.send.return_value = DeliveryResult(
                    "rpt", False, 1, False, True, {}, "rb ok")
                r = MR.return_value
                r.verify.return_value = DeliveryResult(
                    "rpt", True, 0, False, True, {}, "ok")
                rc = cli.main(["report", "--task-id", "AGE-X",
                               "--repo", "o/r", "--pr", "7",
                               "--sections-json", sec, "--state-dir", td])
            self.assertEqual(rc, 0)
            n.send.assert_called_once()
            r.verify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
