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

    def setUp(self):
        p = mock.patch("agentops_runtime.review_intake.trusted_reviewers",
                       return_value={"reviewer", "po-user"})
        p.start()
        self.addCleanup(p.stop)

    def _pr(self, rd=None, mergeable="MERGEABLE", head=None, reviews=None):
        def _with_author(r):
            r = dict(r)
            r.setdefault("author", {"login": "reviewer"})
            return r
        return {"reviewDecision": rd, "mergeable": mergeable,
                "headRefOid": head or self.HEAD,
                "reviews": [_with_author(r) for r in (reviews or [])]}

    def _author(self, login="reviewer"):
        return {"author": {"login": login}}

    def test_approved_pass(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd="APPROVED", reviews=[{"state": "APPROVED",
                                     "commit_id": self.HEAD}]))
        self.assertEqual(r.decision, "PASS")

    def test_approved_stale_head_fail_closed(self):
        # Native APPROVED review bound to an OLDER HEAD is not executable for
        # the current HEAD.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd="APPROVED", reviews=[{"state": "APPROVED",
                                     "commit_id": "oldhead"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

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

    def test_stale_formal_not_pass_not_executable(self):
        # A formal NOT_PASS bound to an OLDER HEAD must NOT drive FIX on the
        # current HEAD (P0-2 regression: previously leaked via the unbounded
        # generic NOT_PASS fallback).
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": "AGENTOPS_REVIEW: NOT_PASS\nHEAD: oldhead"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_formal_missing_head_fail_closed(self):
        # A formal marker with NO HEAD binding is missing/ambiguous.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": "AGENTOPS_REVIEW: PASS"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_generic_comment_not_executable(self):
        # No AGENTOPS_REVIEW marker -> not executable.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED", "body": "looks ok"}]))
        self.assertEqual(r.decision, "INCOMPLETE")

    def test_generic_not_pass_comment_not_executable(self):
        # Generic "NOT PASS" without the formal marker is not executable
        # (P0-2: only the formal AGENTOPS_REVIEW verdict drives decisions).
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[{"state": "COMMENTED",
                               "body": "NOT PASS - please fix styling"}]))
        self.assertEqual(r.decision, "INCOMPLETE")

    def test_native_changes_requested_bound_to_head(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd="CHANGES_REQUESTED", reviews=[
                {"state": "CHANGES_REQUESTED", "commit_id": self.HEAD,
                 "body": "needs work"}]))
        self.assertEqual(r.decision, "CHANGES_REQUESTED")
        self.assertEqual(r.findings, ["needs work"])

    def test_native_changes_requested_stale_head(self):
        # Native CHANGES_REQUESTED review bound to an OLDER HEAD must not
        # drive FIX on the current HEAD.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd="CHANGES_REQUESTED", reviews=[
                {"state": "CHANGES_REQUESTED", "commit_id": "oldhead",
                 "body": "needs work"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_commit_oid_binding_native(self):
        # gh pr view returns reviews with commit.oid (not commit_id).
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd="CHANGES_REQUESTED", reviews=[
                {"state": "CHANGES_REQUESTED",
                 "commit": {"oid": self.HEAD}, "body": "fix it"}]))
        self.assertEqual(r.decision, "CHANGES_REQUESTED")

    def test_commit_oid_binding_stale(self):
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd="CHANGES_REQUESTED", reviews=[
                {"state": "CHANGES_REQUESTED",
                 "commit": {"oid": "oldhead"}, "body": "fix it"}]))
        self.assertEqual(r.decision, "INCOMPLETE")

    def test_latest_formal_review_wins(self):
        # P1-2: among two current-HEAD formal reviews the LATEST (by
        # submittedAt) determines the verdict, not API ordering.
        older = {"state": "COMMENTED",
                 "submittedAt": "2026-08-01T10:00:00Z",
                 "body": f"AGENTOPS_REVIEW: NOT_PASS\nHEAD: {self.HEAD}"}
        newer = {"state": "COMMENTED",
                 "submittedAt": "2026-08-02T10:00:00Z",
                 "body": f"AGENTOPS_REVIEW: PASS\nHEAD: {self.HEAD}"}
        for reviews in ([newer, older], [older, newer]):
            r = review_from_github("o/r", 1, self.HEAD,
                                   self._pr(rd=None, reviews=reviews))
            self.assertEqual(r.decision, "PASS")

    def test_untrusted_formal_pass_fail_closed(self):
        # R6-P0-1: a formal PASS from an untrusted author is not executable.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[self._author("attacker") | {
                "state": "COMMENTED",
                "body": f"AGENTOPS_REVIEW: PASS\nHEAD: {self.HEAD}"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_untrusted_formal_not_pass_fail_closed(self):
        # R6-P0-1: a formal NOT_PASS from an untrusted author cannot drive FIX.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd=None, reviews=[self._author("attacker") | {
                "state": "COMMENTED",
                "body": f"AGENTOPS_REVIEW: NOT_PASS\nHEAD: {self.HEAD}"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_untrusted_native_approved_fail_closed(self):
        # R6-P0-1: native APPROVED from an untrusted author is not executable.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd="APPROVED", reviews=[self._author("attacker") | {
                "state": "APPROVED", "commit_id": self.HEAD}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_untrusted_native_changes_requested_fail_closed(self):
        # R6-P0-1: native CHANGES_REQUESTED from an untrusted author cannot
        # drive FIX.
        r = review_from_github("o/r", 1, self.HEAD, self._pr(
            rd="CHANGES_REQUESTED", reviews=[self._author("attacker") | {
                "state": "CHANGES_REQUESTED", "commit_id": self.HEAD,
                "body": "needs work"}]))
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_missing_author_fail_closed(self):
        # A review with no author identity is untrusted.
        pr_json = {"reviewDecision": None, "mergeable": "MERGEABLE",
                   "headRefOid": self.HEAD,
                   "reviews": [{"state": "COMMENTED",
                                "body": f"AGENTOPS_REVIEW: PASS\nHEAD: {self.HEAD}"}]}
        r = review_from_github("o/r", 1, self.HEAD, pr_json)
        self.assertEqual(r.decision, "INCOMPLETE")


class TestRuntimeLoopDecide(unittest.TestCase):
    def _open_pr(self):
        return mock.patch("agentops_runtime.runtime_loop._pr_state",
                          return_value={"state": "OPEN"})

    def _reviews(self, reviews=None):
        return mock.patch("agentops_runtime.runtime_loop._pr_json_full",
                          return_value={"reviews": reviews or [],
                                        "headRefOid": "abc"})

    def _bridge(self):
        return mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                          return_value=tempfile.mkdtemp())

    def _builder(self):
        return mock.patch("agentops_runtime.runtime_loop.builder_handoff",
                          return_value={"ok": True, "state": "BUILDER_FIXING"})

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
             self._reviews(), self._bridge(), self._builder(), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "FIX")
        self.assertEqual(out["findings"], ["fix"])
        self.assertEqual(out["builder"]["ok"], True)

    def test_auto_pass_passed(self):
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             self._reviews(), self._bridge(), self._builder(), \
             mock.patch("agentops_runtime.runtime_loop._accepted_completion",
                        return_value=False), \
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
             self._reviews(), self._bridge(), \
             mock.patch("agentops_runtime.runtime_loop._po_decision",
                        return_value=None), \
             mock.patch("agentops_runtime.runtime_loop._gate_status_report",
                        return_value={"sent": True, "delivered": True,
                                      "duplicate": False}), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "WAITING_PO_AUTH")
        self.assertTrue(out["checkpoint_reached"])
        self.assertTrue(out["gate_report"]["delivered"])

    def test_gate_status_report_idempotent(self):
        # MANUAL E2E: entering WAITING_PO_AUTH auto-sends ONE gate status
        # report via the existing Neutral Relay, idempotent per exact PR+HEAD.
        from agentops_runtime.runtime_loop import _gate_status_report
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td), \
             mock.patch("agentops_runtime.runtime_loop.relay_client"
                        ".send_status_report",
                        return_value={"delivered": True,
                                      "correlation_id": "c1"}):
            first = _gate_status_report("AGE-X", "o/r", "7", "abc")
            second = _gate_status_report("AGE-X", "o/r", "7", "abc")
        self.assertTrue(first["delivered"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["correlation_id"], "c1")

    def test_gate_status_report_not_sent_for_other_head(self):
        # A gate report bound to a different exact PR+HEAD must send anew.
        from agentops_runtime.runtime_loop import _gate_status_report
        sent = []
        def _fake_send(payload, _out):
            sent.append(1)
            return {"delivered": True, "correlation_id": "c2"}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td), \
             mock.patch("agentops_runtime.runtime_loop.relay_client"
                        ".send_status_report", side_effect=_fake_send):
            first = _gate_status_report("AGE-X", "o/r", "7", "abc")
            other = _gate_status_report("AGE-X", "o/r", "7", "other")
        self.assertFalse(first["duplicate"])
        self.assertFalse(other["duplicate"])
        self.assertEqual(len(sent), 2)

    def test_gate_report_retry_after_failure_then_dedupe(self):
        # R8-1: delivered=false must NOT dedupe. Next cycle retries; once
        # delivered=true, subsequent cycles dedupe.
        from agentops_runtime.runtime_loop import _gate_status_report
        results = [{"delivered": False, "correlation_id": "fail-1"},
                   {"delivered": True, "correlation_id": "ok-2"}]
        def _fake_send(payload, _out):
            return results.pop(0)
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td), \
             mock.patch("agentops_runtime.runtime_loop.relay_client"
                        ".send_status_report", side_effect=_fake_send):
            first = _gate_status_report("AGE-X", "o/r", "7", "abc")
            self.assertFalse(first["delivered"])
            self.assertFalse(first["duplicate"])
            second = _gate_status_report("AGE-X", "o/r", "7", "abc")
            self.assertTrue(second["delivered"])
            self.assertFalse(second["duplicate"])  # retried, not deduped
            third = _gate_status_report("AGE-X", "o/r", "7", "abc")
            self.assertTrue(third["duplicate"])    # now deduped
            self.assertEqual(third["correlation_id"], "ok-2")

    def test_gate_report_stays_waiting_po_auth_on_failure(self):
        # R8-1: on delivered=false the loop stays WAITING_PO_AUTH (no
        # CONTINUE/termination) and the next cycle retries.
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "MANUAL",
                                              "final approval", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             self._reviews(), self._bridge(), \
             mock.patch("agentops_runtime.runtime_loop._po_decision",
                        return_value=None), \
             mock.patch("agentops_runtime.runtime_loop._gate_status_report",
                        return_value={"sent": True, "delivered": False,
                                      "duplicate": False}), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "WAITING_PO_AUTH")
        self.assertTrue(out["checkpoint_reached"])
        self.assertFalse(out["gate_report"]["delivered"])

    def test_manual_resume_after_po_approve(self):
        # P0-2/R5-P0-1: a PO APPROVE decision at the exact HEAD resumes the
        # loop and wakes the Builder to continue (no completion evidence yet).
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "MANUAL",
                                              "final approval", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             self._reviews(), self._bridge(), self._builder(), \
             mock.patch("agentops_runtime.runtime_loop._po_decision",
                        return_value="APPROVE"), \
             mock.patch("agentops_runtime.runtime_loop._accepted_completion",
                        return_value=False), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "PASSED")
        self.assertEqual(out["po_decision"], "APPROVE")
        self.assertEqual(out["builder"]["ok"], True)

    def test_auto_pass_complete_from_evidence(self):
        # R5-P0-1: AUTO PASS produces COMPLETE only from accepted-completion
        # evidence, not from a bare verdict.
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             self._reviews(), \
             mock.patch("agentops_runtime.runtime_loop._accepted_completion",
                        return_value=True), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "COMPLETE")

    def test_auto_pass_wakes_builder_to_continue(self):
        # R5-P0-1: AUTO PASS without completion evidence wakes the Builder
        # (CONTINUE) instead of being terminal.
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             self._reviews(), self._bridge(), self._builder(), \
             mock.patch("agentops_runtime.runtime_loop._accepted_completion",
                        return_value=False), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "PASSED")
        self.assertEqual(out["builder"]["ok"], True)

    def test_manual_no_checkpoint_fails_closed(self):
        # P0-2: a MANUAL task without an evaluable named checkpoint is
        # malformed -> BLOCKED/decision request, not silently PASSED.
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "MANUAL", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             self._reviews(), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "BLOCKED")
        self.assertEqual(out["review_decision"], "CHECKPOINT_UNEVALUABLE")

    def test_manual_unevaluable_checkpoint_fails_closed(self):
        # P0-2: a named checkpoint that does not map to a supported runtime
        # stage must not silently pause at PASS.
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "MANUAL",
                                              "after tax filing", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             self._reviews(), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "BLOCKED")

    def test_manual_deploy_checkpoint_fails_closed(self):
        # R6-P0-2: deploy/go-live is excluded from AGE-30; a MANUAL checkpoint
        # naming it must fail closed (not silently continue forever).
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "MANUAL",
                                              "deploy to production", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "PASS", "o/r", 7, "abc", [])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             self._reviews(), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "BLOCKED")

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
             self._reviews(), \
             mock.patch.object(linear_adapter, "read_linear_issue",
                               return_value={"state_name": "Done",
                                             "state_type": "completed"}), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh"):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "TERMINAL")

    def test_loopx_degraded_is_observable(self):
        # P1-1: a failed LoopX refresh is surfaced in the outcome, never
        # silently swallowed.
        with self._open_pr(), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=TaskSpec("AGE-X", "AUTO", None, [])), \
             mock.patch("agentops_runtime.runtime_loop.read_github_pr",
                        return_value=ReviewOutcome(
                            "COMMENTED", "CHANGES_REQUESTED", "o/r", 7,
                            "abc", ["fix"])), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value="abc"), \
             self._reviews(), self._bridge(), self._builder(), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh",
                        return_value={"ok": False, "detail": "boom"}):
            out = decide("AGE-X", "o/r", "7")
        self.assertEqual(out["phase"], "FIX")
        self.assertEqual(out["loopx"], {"ok": False, "detail": "boom"})


class TestPOIntake(unittest.TestCase):
    def _trusted(self):
        return mock.patch("agentops_runtime.runtime_loop.review_intake"
                          ".trusted_reviewers",
                          return_value={"reviewer", "po-user"})

    def test_po_decision_from_formal_review(self):
        from agentops_runtime.runtime_loop import _po_decision
        reviews = [{"state": "COMMENTED", "commit_id": "abc",
                    "author": {"login": "po-user"},
                    "body": "PO_DECISION: APPROVE\nHEAD: abc"}]
        with self._trusted():
            self.assertEqual(_po_decision("AGE-X", "o/r", "7", "abc", reviews),
                             "APPROVE")

    def test_po_decision_stale_head_ignored(self):
        from agentops_runtime.runtime_loop import _po_decision
        reviews = [{"state": "COMMENTED", "commit_id": "old",
                    "author": {"login": "po-user"},
                    "body": "PO_DECISION: APPROVE\nHEAD: old"}]
        with self._trusted():
            self.assertIsNone(_po_decision("AGE-X", "o/r", "7", "abc", reviews))

    def test_po_decision_untrusted_author_ignored(self):
        # R6-P0-1: an untrusted account cannot inject a PO decision.
        from agentops_runtime.runtime_loop import _po_decision
        reviews = [{"state": "COMMENTED", "commit_id": "abc",
                    "author": {"login": "attacker"},
                    "body": "PO_DECISION: APPROVE\nHEAD: abc"}]
        with self._trusted():
            self.assertIsNone(_po_decision("AGE-X", "o/r", "7", "abc", reviews))


class TestRelayClientACK(unittest.TestCase):
    def _send(self, payload, td, output):
        import types
        fake_uuid = types.SimpleNamespace(
            uuid4=lambda: mock.Mock(hex="deadbeefcafe"))
        out = os.path.join(td, "CPL_deadbeefcafe_output.md")
        with open(out, "w") as f:
            f.write(output)
        with mock.patch("agentops_runtime.relay_client.subprocess.run",
                        return_value=mock.Mock(returncode=0)), \
             mock.patch("agentops_runtime.relay_client.RELAY_BIN", "/bin/true"), \
             mock.patch.object(relay_client, "uuid", fake_uuid):
            return relay_client.send_status_report(payload, td)

    def test_ack_exact_binding_delivered(self):
        payload = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                   "REQUEST: status_report\n")
        output = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                  "ACK: status_report_received\n")
        with tempfile.TemporaryDirectory() as td:
            res = self._send(payload, td, output)
        self.assertTrue(res["delivered"])

    def test_ack_wrong_head_not_delivered(self):
        # P0-3: ACK with a different HEAD must not be delivered=true.
        payload = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                   "REQUEST: status_report\n")
        output = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: WRONG\n"
                  "ACK: status_report_received\n")
        with tempfile.TemporaryDirectory() as td:
            res = self._send(payload, td, output)
        self.assertFalse(res["delivered"])

    def test_ack_missing_marker_not_delivered(self):
        payload = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                   "REQUEST: status_report\n")
        output = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                  "ACK: something_else\n")
        with tempfile.TemporaryDirectory() as td:
            res = self._send(payload, td, output)
        self.assertFalse(res["delivered"])

    def test_ack_report_id_alias_not_accepted(self):
        # R5-P0-3: REPORT_ID is NOT an alias for REVIEW_REQUEST_ID.
        payload = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                   "REQUEST: status_report\n")
        output = ("REPORT_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                  "ACK: status_report_received\n")
        with tempfile.TemporaryDirectory() as td:
            res = self._send(payload, td, output)
        self.assertFalse(res["delivered"])

    def test_ack_missing_field_not_delivered(self):
        # R5-P0-3: missing one canonical field -> not delivered.
        payload = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                   "REQUEST: status_report\n")
        output = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\n"
                  "ACK: status_report_received\n")
        with tempfile.TemporaryDirectory() as td:
            res = self._send(payload, td, output)
        self.assertFalse(res["delivered"])

    def test_ack_extra_lines_not_delivered(self):
        # R6-P1: an extra/duplicate non-envelope line fails closed.
        payload = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                   "REQUEST: status_report\n")
        output = ("REVIEW_REQUEST_ID: req-1\nREPO: o/r\nPR: 7\nHEAD: h1\n"
                  "ACK: status_report_received\nEXTRA: noise\n")
        with tempfile.TemporaryDirectory() as td:
            res = self._send(payload, td, output)
        self.assertFalse(res["delivered"])


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

    def test_po_decision_writes_bridge_file(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td):
            rc = cli.main(["po-decision", "--repo", "o/r", "--pr", "7",
                           "--head", "abc", "--decision", "APPROVE"])
            with open(os.path.join(td, "po_decision.json")) as f:
                import json as _json
                d = _json.load(f)
        self.assertEqual(rc, 0)
        self.assertEqual(d["decision"], "APPROVE")
        self.assertEqual(d["head"], "abc")

    def test_complete_writes_bridge_file(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td):
            rc = cli.main(["complete", "--repo", "o/r", "--pr", "7",
                           "--head", "abc"])
            with open(os.path.join(td, "completion.json")) as f:
                import json as _json
                d = _json.load(f)
        self.assertEqual(rc, 0)
        self.assertEqual(d["completion"], "COMPLETE")
        self.assertEqual(d["head"], "abc")

    def test_final_result_review_uses_auto_review(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td):
            p = os.path.join(td, "status.txt")
            with open(p, "w") as f:
                f.write("REVIEW_REQUEST_ID: x\nREPO: o/r\nPR: 7\nHEAD: h\n"
                        "REQUEST: status_report\nSTATE: WAITING_REVIEW\n")
            with mock.patch("agentops_runtime.__main__.relay_client"
                            ".final_result_auto_review",
                            return_value={"status_delivered": True,
                                          "review_sent": True,
                                          "succeeded": True,
                                          "review": {"verdict": "PASS",
                                                     "ok": True}}):
                rc = cli.main(["final-result-review", "--repo", "o/r",
                               "--pr", "7", "--head", "h",
                               "--status-report", p, "--timeout", "10"])
        self.assertEqual(rc, 0)

    def test_final_result_review_nonzero_on_status_failure(self):
        # P1-1: status_report not delivered -> non-zero exit.
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td):
            p = os.path.join(td, "status.txt")
            with open(p, "w") as f:
                f.write("REVIEW_REQUEST_ID: x\nREPO: o/r\nPR: 7\nHEAD: h\n"
                        "REQUEST: status_report\nSTATE: WAITING_REVIEW\n")
            with mock.patch("agentops_runtime.__main__.relay_client"
                            ".final_result_auto_review",
                            return_value={"status_delivered": False,
                                          "review_sent": False}):
                rc = cli.main(["final-result-review", "--repo", "o/r",
                               "--pr", "7", "--head", "h",
                               "--status-report", p, "--timeout", "10"])
        self.assertEqual(rc, 1)

    def test_final_result_review_nonzero_on_parse_failure(self):
        # P1-1: independent_review sent but parse failed -> non-zero exit.
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td):
            p = os.path.join(td, "status.txt")
            with open(p, "w") as f:
                f.write("REVIEW_REQUEST_ID: x\nREPO: o/r\nPR: 7\nHEAD: h\n"
                        "REQUEST: status_report\nSTATE: WAITING_REVIEW\n")
            with mock.patch("agentops_runtime.__main__.relay_client"
                            ".final_result_auto_review",
                            return_value={"status_delivered": True,
                                          "review_sent": True,
                                          "succeeded": False,
                                          "review": {"verdict": "INCOMPLETE",
                                                     "ok": False}}):
                rc = cli.main(["final-result-review", "--repo", "o/r",
                               "--pr", "7", "--head", "h",
                               "--status-report", p, "--timeout", "10"])
        self.assertEqual(rc, 2)


class TestParseReviewResponse(unittest.TestCase):
    def _text(self, verdict="PASS", req="AR-1", repo="o/r", pr="7",
              head="abc", findings=""):
        lines = [f"AGENTOPS_REVIEW: {verdict}", f"HEAD: {head}",
                 f"REVIEW_REQUEST_ID: {req}", f"REPO: {repo}", f"PR: {pr}"]
        if findings:
            lines.append(findings)
        return "\n".join(lines)

    def test_pass_parsed(self):
        r = relay_client.parse_review_response(
            self._text(), "o/r", "7", "abc", "AR-1")
        self.assertEqual(r["verdict"], "PASS")
        self.assertTrue(r["ok"])

    def test_changes_requested_findings_retained(self):
        r = relay_client.parse_review_response(
            self._text(verdict="CHANGES_REQUESTED",
                       findings="- fix P0-1\n- also P0-2"),
            "o/r", "7", "abc", "AR-1")
        self.assertEqual(r["verdict"], "CHANGES_REQUESTED")
        self.assertEqual(r["findings"], ["- fix P0-1", "- also P0-2"])

    def test_not_pass_findings_retained(self):
        r = relay_client.parse_review_response(
            self._text(verdict="NOT_PASS", findings="blocked reason"),
            "o/r", "7", "abc", "AR-1")
        self.assertEqual(r["verdict"], "NOT_PASS")
        self.assertEqual(r["findings"], ["blocked reason"])

    def test_head_mismatch_fail_closed(self):
        r = relay_client.parse_review_response(
            self._text(head="WRONG"), "o/r", "7", "abc", "AR-1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["verdict"], "INCOMPLETE")

    def test_req_id_mismatch_fail_closed(self):
        r = relay_client.parse_review_response(
            self._text(req="OTHER"), "o/r", "7", "abc", "AR-1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["verdict"], "INCOMPLETE")

    def test_missing_verdict_fail_closed(self):
        r = relay_client.parse_review_response(
            "REVIEW_REQUEST_ID: AR-1\nREPO: o/r\nPR: 7\nHEAD: abc\n",
            "o/r", "7", "abc", "AR-1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["verdict"], "INCOMPLETE")

    def test_invalid_verdict_fail_closed(self):
        r = relay_client.parse_review_response(
            self._text(verdict="MAYBE"), "o/r", "7", "abc", "AR-1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["verdict"], "INCOMPLETE")

    def test_duplicate_verdict_fail_closed(self):
        r = relay_client.parse_review_response(
            self._text(verdict="PASS") + "\nAGENTOPS_REVIEW: PASS",
            "o/r", "7", "abc", "AR-1")
        self.assertFalse(r["ok"])

    def test_duplicate_head_fail_closed(self):
        r = relay_client.parse_review_response(
            self._text() + "\nHEAD: abc", "o/r", "7", "abc", "AR-1")
        self.assertFalse(r["ok"])


class TestFinalResultAutoReview(unittest.TestCase):
    STATUS_WAITING = ("REVIEW_REQUEST_ID: s1\nREPO: o/r\nPR: 7\nHEAD: h\n"
                      "REQUEST: status_report\nSTATE: WAITING_REVIEW\n")
    STATUS_WAITING_PO = ("REVIEW_REQUEST_ID: s1\nREPO: o/r\nPR: 7\nHEAD: h\n"
                         "REQUEST: status_report\nSTATE: WAITING_PO_AUTH\n")

    def test_waiting_review_ack_success_review_once(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review",
                            return_value={"sent": True,
                                          "review_request_id": "AR-1",
                                          "raw_response":
                                              "AGENTOPS_REVIEW: PASS\n"
                                              "HEAD: h\n"
                                              "REVIEW_REQUEST_ID: AR-1\n"
                                              "REPO: o/r\nPR: 7\n"}):
                r = relay_client.final_result_auto_review(
                    "o/r", "7", "h", self.STATUS_WAITING, td,
                    os.path.join(td, "out"))
        self.assertTrue(r["status_delivered"])
        self.assertTrue(r["review_sent"])
        self.assertEqual(r["review"]["verdict"], "PASS")

    def test_ack_failure_no_review(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": False,
                                          "detail": "no ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review") as m:
                r = relay_client.final_result_auto_review(
                    "o/r", "7", "h", self.STATUS_WAITING, td,
                    os.path.join(td, "out"))
        self.assertFalse(r["status_delivered"])
        self.assertFalse(r["review_sent"])
        m.assert_not_called()

    def test_waiting_po_ack_success_no_review(self):
        # WAITING_PO_AUTH even delivered=true must NOT trigger a review.
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review") as m:
                r = relay_client.final_result_auto_review(
                    "o/r", "7", "h", self.STATUS_WAITING_PO, td,
                    os.path.join(td, "out"))
        self.assertTrue(r["status_delivered"])
        self.assertFalse(r["review_sent"])
        m.assert_not_called()

    def test_duplicate_invocation_no_duplicate_review(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            def _fake_send(*a, **k):
                calls.append(a)
                return {"sent": True, "review_request_id": "AR-1",
                        "exit_code": 0,
                        "raw_response": "AGENTOPS_REVIEW: PASS\nHEAD: h\n"
                                        "REVIEW_REQUEST_ID: AR-1\n"
                                        "REPO: o/r\nPR: 7\n"}
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review", side_effect=_fake_send):
                first = relay_client.final_result_auto_review(
                    "o/r", "7", "h", self.STATUS_WAITING, td,
                    os.path.join(td, "out"))
                second = relay_client.final_result_auto_review(
                    "o/r", "7", "h", self.STATUS_WAITING, td,
                    os.path.join(td, "out"))
        self.assertTrue(first["review_sent"])
        self.assertTrue(second["deduped"])
        self.assertFalse(second["review_sent"])
        self.assertEqual(len(calls), 1)

    def test_review_failure_stays_retryable(self):
        # P0-1: a failed independent_review (relay non-zero exit OR INCOMPLETE
        # parse) must NOT write the success dedupe marker; the next invocation
        # must actually re-send.
        with tempfile.TemporaryDirectory() as td:
            calls = []
            def _fake_send(*a, **k):
                calls.append(a)
                return {"sent": True, "review_request_id": "AR-1",
                        "exit_code": 1,  # relay failed
                        "raw_response": ""}
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review", side_effect=_fake_send):
                first = relay_client.final_result_auto_review(
                    "o/r", "7", "h", self.STATUS_WAITING, td,
                    os.path.join(td, "out"))
                second = relay_client.final_result_auto_review(
                    "o/r", "7", "h", self.STATUS_WAITING, td,
                    os.path.join(td, "out"))
        self.assertFalse(first["succeeded"])
        self.assertFalse(first["deduped"])
        self.assertFalse(second["deduped"])
        self.assertTrue(second["review_sent"])  # retried, not deduped
        self.assertEqual(len(calls), 2)

    def test_review_parse_incomplete_stays_retryable(self):
        # P0-1: relay succeeded but the response failed strict parse
        # (binding mismatch) -> not deduped, retried on next invocation.
        with tempfile.TemporaryDirectory() as td:
            calls = []
            def _fake_send(*a, **k):
                calls.append(a)
                return {"sent": True, "review_request_id": "AR-1",
                        "exit_code": 0,
                        "raw_response": "AGENTOPS_REVIEW: PASS\nHEAD: WRONG\n"
                                        "REVIEW_REQUEST_ID: AR-1\n"
                                        "REPO: o/r\nPR: 7\n"}
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review", side_effect=_fake_send):
                first = relay_client.final_result_auto_review(
                    "o/r", "7", "h", self.STATUS_WAITING, td,
                    os.path.join(td, "out"))
                second = relay_client.final_result_auto_review(
                    "o/r", "7", "h", self.STATUS_WAITING, td,
                    os.path.join(td, "out"))
        self.assertFalse(first["succeeded"])
        self.assertEqual(first["review"]["verdict"], "INCOMPLETE")
        self.assertFalse(second["deduped"])
        self.assertEqual(len(calls), 2)

    def _status_payload(self, repo="o/r", pr="7", head="h", req="status_report",
                        state="WAITING_REVIEW"):
        return (f"REVIEW_REQUEST_ID: s1\nREPO: {repo}\nPR: {pr}\nHEAD: {head}\n"
                f"REQUEST: {req}\nSTATE: {state}\n")

    def test_repo_mismatch_no_review(self):
        # R12-P0: status payload REPO != invocation repo -> fail closed, no
        # independent_review even though ACK succeeded.
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review") as m:
                r = relay_client.final_result_auto_review(
                    "o/r", "7", "h",
                    self._status_payload(repo="OTHER"), td,
                    os.path.join(td, "out"))
        self.assertTrue(r["status_delivered"])
        self.assertFalse(r["review_sent"])
        self.assertFalse(r["binding_ok"])
        m.assert_not_called()

    def test_pr_mismatch_no_review(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review") as m:
                r = relay_client.final_result_auto_review(
                    "o/r", "7", "h",
                    self._status_payload(pr="99"), td,
                    os.path.join(td, "out"))
        self.assertFalse(r["review_sent"])
        self.assertFalse(r["binding_ok"])
        m.assert_not_called()

    def test_head_mismatch_no_review(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review") as m:
                r = relay_client.final_result_auto_review(
                    "o/r", "7", "h",
                    self._status_payload(head="WRONG"), td,
                    os.path.join(td, "out"))
        self.assertFalse(r["review_sent"])
        self.assertFalse(r["binding_ok"])
        m.assert_not_called()

    def test_missing_field_no_review(self):
        payload = ("REVIEW_REQUEST_ID: s1\nREPO: o/r\nPR: 7\n"
                   "REQUEST: status_report\nSTATE: WAITING_REVIEW\n")  # HEAD missing
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review") as m:
                r = relay_client.final_result_auto_review(
                    "o/r", "7", "h", payload, td,
                    os.path.join(td, "out"))
        self.assertFalse(r["review_sent"])
        self.assertFalse(r["binding_ok"])
        m.assert_not_called()

    def test_duplicate_field_no_review(self):
        payload = ("REVIEW_REQUEST_ID: s1\nREPO: o/r\nPR: 7\nHEAD: h\n"
                   "HEAD: h2\nREQUEST: status_report\nSTATE: WAITING_REVIEW\n")
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review") as m:
                r = relay_client.final_result_auto_review(
                    "o/r", "7", "h", payload, td,
                    os.path.join(td, "out"))
        self.assertFalse(r["review_sent"])
        self.assertFalse(r["binding_ok"])
        m.assert_not_called()

    def test_wrong_request_no_review(self):
        payload = self._status_payload(req="independent_review")
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.relay_client.send_status_report",
                            return_value={"delivered": True,
                                          "detail": "ack"}), \
                 mock.patch("agentops_runtime.relay_client"
                            ".send_independent_review") as m:
                r = relay_client.final_result_auto_review(
                    "o/r", "7", "h", payload, td,
                    os.path.join(td, "out"))
        self.assertFalse(r["review_sent"])
        m.assert_not_called()


if __name__ == "__main__":
    unittest.main()
