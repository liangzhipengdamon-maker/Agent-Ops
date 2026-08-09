import unittest
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from risk_evaluator import classify_risk, RiskDecision
from review_intake import review_from_github, ReviewDecision
from task_intake import is_eligible, discover, write_discovery_records
from transition_controller import route_decision, TransitionOutcome, write_state


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


if __name__ == "__main__":
    unittest.main()
