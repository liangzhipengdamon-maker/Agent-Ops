import unittest
import os
import sys
import tempfile
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

import agentops_runtime.__main__ as cli
from agentops_runtime import linear_adapter, review_intake, relay_client
from agentops_runtime.task_intake import (parse_mode, extract_checkpoint,
                                          spec_from_linear, TaskSpec)
from agentops_runtime.review_intake import review_from_github, ReviewOutcome
from agentops_runtime.runtime_loop import decide
from agentops_runtime.controller import ControlWatcher


AUTO_DESC = """# Task

Execution Mode: AUTO

Acceptance criteria:
- The AUTO sandbox task is picked up and executed
- PASS continues in scope
"""

MANUAL_DESC = """# Task

Execution Mode: MANUAL
checkpoint: final approval

Acceptance criteria:
- Pauses only at the named checkpoint
- Resumes after PO decision
"""


class TestTaskIntake(unittest.TestCase):
    def test_parse_mode_auto(self):
        self.assertEqual(parse_mode(AUTO_DESC), "AUTO")

    def test_parse_mode_manual(self):
        self.assertEqual(parse_mode(MANUAL_DESC), "MANUAL")

    def test_parse_mode_ambiguous_returns_empty(self):
        self.assertEqual(parse_mode("AUTO and MANUAL both"), "")

    def test_parse_mode_missing_returns_empty(self):
        self.assertEqual(parse_mode("no mode"), "")

    def test_extract_checkpoint(self):
        self.assertEqual(extract_checkpoint(MANUAL_DESC), "final approval")

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

    def test_formal_comment_pass(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": f"AGENTOPS_REVIEW: PASS\nHEAD: {self.HEAD}"}]))
        self.assertEqual(r.decision, "PASS")

    def test_formal_comment_changes_requested(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": f"AGENTOPS_REVIEW: CHANGES_REQUESTED\nHEAD: {self.HEAD}"}]))
        self.assertEqual(r.decision, "CHANGES_REQUESTED")

    def test_formal_comment_not_pass(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": f"AGENTOPS_REVIEW: NOT_PASS\nHEAD: {self.HEAD}"}]))
        self.assertEqual(r.decision, "NOT_PASS")

    def test_stale_head_fail_closed(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": "AGENTOPS_REVIEW: PASS\nHEAD: oldhead"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_generic_comment_not_executable(self):
        # No AGENTOPS_REVIEW marker -> not executable.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED", "body": "looks ok"}]))
        self.assertEqual(r.decision, "INCOMPLETE")


class TestRuntimeLoopDecide(unittest.TestCase):
    def _open_pr(self):
        return mock.patch("agentops_runtime.runtime_loop._pr_state",
                          return_value={"state": "OPEN"})

    def test_auto_review_fix(self):
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "CHANGES_REQUESTED", "o/r", 7,
                            "abc", ["fix"])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "FIX")
        self.assertEqual(out["findings"], ["fix"])

    def test_auto_pass_passed(self):
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "PASSED")

    def test_manual_pause_at_checkpoint(self):
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "MANUAL",
                                              "final approval", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "WAITING_PO_AUTH")
        self.assertTrue(out["checkpoint_reached"])

    def test_manual_no_checkpoint_does_not_pause(self):
        # MANUAL without a named checkpoint must not pause.
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "MANUAL", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "PASSED")

    def test_unreadable_remote_blocked(self):
        with mock.patch("agentops_runtime.runtime_loop._pr_state",
                        return_value=None), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "BLOCKED")

    def test_closed_pr_terminal(self):
        with mock.patch("agentops_runtime.runtime_loop._pr_state",
                        return_value={"state": "CLOSED"}), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "TERMINAL")

    def test_task_closed_terminal(self):
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             mock.patch.object(linear_adapter, "read_linear_issue",
                               return_value={"state_name": "Done",
                                             "state_type": "completed"}), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "TERMINAL")


class TestCLIEntrypoint(unittest.TestCase):
    def test_run_auto_mode_missing_surfaces_decision(self):
        with mock.patch("agentops_runtime.__main__.decide",
                        return_value={"phase": "BLOCKED",
                                      "decision_request": "specify mode"}):
            rc = cli.main(["run-auto", "--task-id", "AGE-X",
                           "--repo", "o/r", "--pr", "7"])
        self.assertEqual(rc, 0)  # decision surfaced in output

    def test_watch_requires_no_extra_args(self):
        with mock.patch("agentops_runtime.__main__.ControlWatcher") as MC:
            inst = MC.return_value
            inst.run_forever.return_value = True
            rc = cli.main(["watch", "--task-id", "AGE-X",
                           "--repo", "o/r", "--pr", "7",
                           "--interval", "600"])
        self.assertEqual(rc, 0)
        MC.assert_called_once()

    def test_report_uses_relay_client(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "status.txt")
            with open(p, "w") as f:
                f.write("REVIEW_REQUEST_ID: x\nREPO: o/r\nPR: 7\nHEAD: h\n"
                        "REQUEST: status_report\nSTATE: WAITING_PO_AUTH\n")
            with mock.patch("agentops_runtime.__main__.relay_client"
                            ".send_status_report",
                            return_value={"correlation_id": "x",
                                          "delivered": True}):
                rc = cli.main(["report", "--task-id", "AGE-X",
                               "--repo", "o/r", "--pr", "7",
                               "--status-report", p])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
