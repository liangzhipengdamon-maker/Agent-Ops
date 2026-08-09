import unittest
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from risk_evaluator import classify_risk, RiskDecision
from review_intake import review_from_github, ReviewDecision
from task_intake import is_eligible, discover, write_discovery_records
from transition_controller import (
    route_decision, TransitionOutcome, write_state,
    build_completion_report, NeutralRelayNotifier, DeliveryResult,
    transition_with_po_notify,
)


class TestRiskEvaluator(unittest.TestCase):
    def test_no_factors_low(self):
        d = classify_risk()
        self.assertEqual(d.level, "LOW")

    def test_production_code_low(self):
        d = classify_risk(production_code=True)
        self.assertEqual(d.level, "MEDIUM")  # flagged but not always-high -> MEDIUM

    def test_deployment_high(self):
        d = classify_risk(deployment=True)
        self.assertEqual(d.level, "HIGH")

    def test_merge_high(self):
        d = classify_risk(merge_action=True)
        self.assertEqual(d.level, "HIGH")

    def test_authorization_change_high(self):
        d = classify_risk(authorization_change=True)
        self.assertEqual(d.level, "HIGH")

    def test_security_boundary_medium(self):
        d = classify_risk(security_boundary=True)
        self.assertEqual(d.level, "MEDIUM")

    def test_unknown_impact_fail_closed_high(self):
        d = classify_risk(unknown_impact=True)
        self.assertEqual(d.level, "HIGH")
        self.assertTrue(d.fail_closed)

    def test_high_wins_over_medium(self):
        d = classify_risk(security_boundary=True, merge_action=True)
        self.assertEqual(d.level, "HIGH")

    def test_explicit_high_respected(self):
        d = classify_risk(explicit_level="HIGH")
        self.assertEqual(d.level, "HIGH")

    def test_explicit_unknown_fail_closed(self):
        d = classify_risk(explicit_level="WTF")
        self.assertEqual(d.level, "HIGH")
        self.assertTrue(d.fail_closed)

    def test_never_grants(self):
        # The decision carries no permission flag.
        d = classify_risk(deployment=True)
        self.assertNotIn("authorized", dir(d))


class TestReviewIntake(unittest.TestCase):
    HEAD = "abc123def"

    def test_approved_pass(self):
        r = review_from_github("o/r", 1, self.HEAD, {
            "headRefOid": self.HEAD, "reviewDecision": "APPROVED",
            "mergeable": "MERGEABLE"})
        self.assertEqual(r.decision, "PASS")
        self.assertEqual(r.state, "APPROVED")
        self.assertFalse(r.fail_closed)

    def test_changes_requested(self):
        r = review_from_github("o/r", 1, self.HEAD, {
            "headRefOid": self.HEAD, "reviewDecision": "CHANGES_REQUESTED",
            "mergeable": "MERGEABLE"})
        self.assertEqual(r.decision, "CHANGES_REQUESTED")

    def test_head_mismatch_fail_closed(self):
        r = review_from_github("o/r", 1, self.HEAD, {
            "headRefOid": "other", "reviewDecision": "APPROVED",
            "mergeable": "MERGEABLE"})
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_conflict_fail_closed(self):
        r = review_from_github("o/r", 1, self.HEAD, {
            "headRefOid": self.HEAD, "reviewDecision": "APPROVED",
            "mergeable": "CONFLICTING"})
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_no_json_fail_closed(self):
        r = review_from_github("o/r", 1, self.HEAD, None)
        self.assertEqual(r.decision, "INCOMPLETE")
        self.assertTrue(r.fail_closed)

    def test_review_required_incomplete(self):
        r = review_from_github("o/r", 1, self.HEAD, {
            "headRefOid": self.HEAD, "reviewDecision": None,
            "mergeable": "MERGEABLE"})
        self.assertEqual(r.decision, "INCOMPLETE")


class TestTaskIntake(unittest.TestCase):
    def test_eligible_backlog(self):
        self.assertTrue(is_eligible({"id": "AGE-1", "title": "x", "state": "Backlog"}, "o/r"))

    def test_todo_eligible(self):
        self.assertTrue(is_eligible({"id": "AGE-1", "title": "x", "state": "Todo"}, "o/r"))

    def test_done_not_eligible(self):
        self.assertFalse(is_eligible({"id": "AGE-1", "title": "x", "state": "Done"}, "o/r"))

    def test_no_title_not_eligible(self):
        self.assertFalse(is_eligible({"id": "AGE-1", "title": "", "state": "Backlog"}, "o/r"))

    def test_in_progress_not_eligible(self):
        self.assertFalse(is_eligible({"id": "AGE-1", "title": "x", "state": "In Progress"}, "o/r"))

    def test_discover_filters(self):
        issues = [
            {"id": "AGE-1", "title": "a", "state": "Backlog"},
            {"id": "AGE-2", "title": "b", "state": "Done"},
            {"id": "AGE-3", "title": "c", "state": "Todo"},
        ]
        tasks = discover(issues, "o/r")
        ids = {t.linear_issue for t in tasks}
        self.assertEqual(ids, {"AGE-1", "AGE-3"})

    def test_write_discovery_records(self):
        with tempfile.TemporaryDirectory() as td:
            tasks = discover([{"id": "AGE-1", "title": "a", "state": "Backlog"}], "o/r")
            written = write_discovery_records(tasks, td)
            self.assertEqual(len(written), 1)
            with open(written[0]) as f:
                record = json.load(f)
            self.assertEqual(record["type"], "TASK_DISCOVERED")
            self.assertEqual(record["linear_issue"], "AGE-1")


class TestTransitionController(unittest.TestCase):
    def test_high_routes_po_auth(self):
        o = route_decision("HIGH", "PASS")
        self.assertEqual(o.route, "WAITING_PO_AUTH")

    def test_medium_routes_gpt(self):
        o = route_decision("MEDIUM", "PASS")
        self.assertEqual(o.route, "GPT_DECISION_REQUIRED")

    def test_low_pass_auto_continue(self):
        o = route_decision("LOW", "PASS")
        self.assertEqual(o.route, "AUTO_CONTINUE")

    def test_low_changes_requested_follow_up(self):
        o = route_decision("LOW", "CHANGES_REQUESTED")
        self.assertEqual(o.route, "FOLLOW_UP_REQUIRED")

    def test_low_incomplete_wait(self):
        o = route_decision("LOW", "INCOMPLETE")
        self.assertEqual(o.route, "WAIT_REVIEW")

    def test_write_state(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "task_state.json")
            o = route_decision("HIGH", "PASS")
            write_state(o, path)
            with open(path) as f:
                state = json.load(f)
            self.assertEqual(state["outcome"]["route"], "WAITING_PO_AUTH")


class TestPoNotifyBeforeWait(unittest.TestCase):
    """AGE-30 hardening: mandatory PO notification before WAITING_PO_AUTH."""

    class FakeNotifier:
        def __init__(self, ack=True, exit_code=0):
            self.sent = []
            self.ack = ack
            self.exit_code = exit_code

        def send(self, report, output_dir):
            self.sent.append(report)
            return DeliveryResult(
                correlation_id=report.correlation_id,
                delivered=self.ack, exit_code=self.exit_code,
                ack_captured=self.ack, readback_confirmed=False,
                readback_checks={},
                details="fake-ack" if self.ack else "fake-no-ack")

    class FakeReadback:
        def __init__(self, confirmed=True):
            self.confirmed = confirmed

        def verify(self, report):
            return DeliveryResult(
                correlation_id=report.correlation_id,
                delivered=self.confirmed, exit_code=0,
                ack_captured=False, readback_confirmed=self.confirmed,
                readback_checks={
                    "correlation_id": self.confirmed,
                    "pr": self.confirmed,
                    "head": self.confirmed,
                    "deliverable_path": self.confirmed,
                    "end_marker": self.confirmed,
                },
                details="readback_confirmed" if self.confirmed else "readback_missing")

    def _sections(self):
        return {
            "Task": "AGE-30 notify validation",
            "Fixed behavior": "notify before WAITING_PO_AUTH",
            "Implementation": "transition_controller.py",
            "Live validation evidence": "correlation delivered",
            "Requirements verification": "all met",
            "PR/branch/HEAD": "pr 1 / feat/x / abc",
            "CI": "pass",
            "Deliverable": "docs/plans/AGE30_REPORT.md",
            "Boundaries": "no merge, no deploy",
        }

    def test_build_completion_report_binds_fields(self):
        r = build_completion_report(
            task_id="AGE-X", repo="o/r", pr="1", head="abc",
            deliverable_path="docs/plans/X.md",
            deliverable_url="https://github.com/o/r/blob/main/docs/plans/X.md",
            sections=self._sections())
        self.assertEqual(r.repo, "o/r")
        self.assertEqual(r.pr, "1")
        self.assertEqual(r.head, "abc")
        self.assertEqual(r.deliverable_path, "docs/plans/X.md")
        self.assertTrue(r.end_marker.startswith("AGENTOPS_COMPLETION_REPORT_END_"))
        payload = r.to_relay_payload()
        self.assertIn("REVIEW_REQUEST_ID:", payload)
        self.assertIn("HEAD: abc", payload)
        self.assertIn("DELIVERABLE_PATH: docs/plans/X.md", payload)
        self.assertIn("DELIVERABLE_URL:", payload)
        self.assertIn(r.end_marker, payload)
        # Concise: body is NOT the full report; only a compact summary.
        self.assertLess(len(r.body), 1500)

    def test_high_risk_always_notifies_and_confirms(self):
        notifier = self.FakeNotifier(ack=True)
        readback = self.FakeReadback(confirmed=True)
        with tempfile.TemporaryDirectory() as td:
            result = transition_with_po_notify(
                risk_level="HIGH", review_decision="PASS",
                task_id="AGE-X", repo="o/r", pr="1", head="abc",
                deliverable_path="docs/plans/X.md",
                deliverable_url="https://github.com/o/r/blob/main/docs/plans/X.md",
                completion_sections=self._sections(), output_dir=td,
                notifier=notifier, readback=readback,
                task_state_path=os.path.join(td, "state.json"))
        self.assertEqual(result["outcome"]["route"], "WAITING_PO_AUTH")
        self.assertEqual(result["po_notify"]["status"], "DELIVERED")
        self.assertTrue(result["po_notify"]["delivered"])
        self.assertEqual(len(notifier.sent), 1)

    def test_high_risk_readback_alone_confirms_delivery(self):
        # Even if relay ack is not captured, a read-back confirmation
        # upgrades delivery to confirmed (never fake).
        notifier = self.FakeNotifier(ack=False, exit_code=1)
        readback = self.FakeReadback(confirmed=True)
        with tempfile.TemporaryDirectory() as td:
            result = transition_with_po_notify(
                risk_level="HIGH", review_decision="PASS",
                task_id="AGE-X", repo="o/r", pr="1", head="abc",
                deliverable_path="docs/plans/X.md",
                deliverable_url="https://github.com/o/r/blob/main/docs/plans/X.md",
                completion_sections=self._sections(), output_dir=td,
                notifier=notifier, readback=readback)
        self.assertEqual(result["po_notify"]["status"], "DELIVERED")
        self.assertTrue(result["po_notify"]["readback_confirmed"])

    def test_medium_risk_does_not_notify_po(self):
        notifier = self.FakeNotifier()
        with tempfile.TemporaryDirectory() as td:
            result = transition_with_po_notify(
                risk_level="MEDIUM", review_decision="PASS",
                task_id="AGE-X", repo="o/r", pr="1", head="abc",
                deliverable_path="docs/plans/X.md",
                deliverable_url="https://github.com/o/r/blob/main/docs/plans/X.md",
                completion_sections=self._sections(), output_dir=td,
                notifier=notifier)
        self.assertEqual(result["outcome"]["route"], "GPT_DECISION_REQUIRED")
        self.assertNotIn("po_notify", result)
        self.assertEqual(len(notifier.sent), 0)

    def test_low_pass_no_notify(self):
        notifier = self.FakeNotifier()
        with tempfile.TemporaryDirectory() as td:
            result = transition_with_po_notify(
                risk_level="LOW", review_decision="PASS",
                task_id="AGE-X", repo="o/r", pr="1", head="abc",
                deliverable_path="docs/plans/X.md",
                deliverable_url="https://github.com/o/r/blob/main/docs/plans/X.md",
                completion_sections=self._sections(), output_dir=td,
                notifier=notifier)
        self.assertEqual(result["outcome"]["route"], "AUTO_CONTINUE")
        self.assertNotIn("po_notify", result)
        self.assertEqual(len(notifier.sent), 0)

    def test_delivery_failure_marks_failed_not_fake(self):
        # P0 fail-closed: no ack AND no read-back confirmation -> DELIVERY_FAILED
        # and the state must NOT be recorded as WAITING_PO_AUTH.
        notifier = self.FakeNotifier(ack=False, exit_code=1)
        readback = self.FakeReadback(confirmed=False)
        with tempfile.TemporaryDirectory() as td:
            result = transition_with_po_notify(
                risk_level="HIGH", review_decision="PASS",
                task_id="AGE-X", repo="o/r", pr="1", head="abc",
                deliverable_path="docs/plans/X.md",
                deliverable_url="https://github.com/o/r/blob/main/docs/plans/X.md",
                completion_sections=self._sections(), output_dir=td,
                notifier=notifier, readback=readback,
                task_state_path=os.path.join(td, "state.json"))
        self.assertEqual(result["outcome"]["route"], "DELIVERY_FAILED")
        self.assertEqual(result["po_notify"]["status"], "DELIVERY_FAILED")
        self.assertFalse(result["po_notify"]["delivered"])
        self.assertEqual(len(notifier.sent), 1)


if __name__ == "__main__":
    unittest.main()
