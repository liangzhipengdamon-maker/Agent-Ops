import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from agentops_runtime import lifecycle_guard, runtime_loop
from agentops_runtime.controller import ControlWatcher
from governloop_runtime.__main__ import build_parser
from agentops_runtime.task_intake import TaskSpec

REPO = "owner/repo"
PR = "42"
HEAD = "0123456789abcdef0123456789abcdef01234567"


def signed_payload(decision="APPROVE", action=None, *, head=HEAD):
    payload = {
        "schema": lifecycle_guard.PO_SCHEMA,
        "repo": REPO,
        "pr": PR,
        "head": head,
        "decision": decision,
    }
    if action:
        payload["lifecycle_action"] = action
    return {"ok": True, "payload": payload, "detail": "verified"}


class GateMixin:
    def _write(self, td, name, data):
        with open(os.path.join(td, name), "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def _gate(self, td, *, head=HEAD, delivered=True):
        self._write(td, "gate_report.json", {
            "repo": REPO, "pr": PR, "head": head,
            "sent": True, "delivered": delivered,
        })


class TestManualLifecycleGuard(GateMixin, unittest.TestCase):
    def setUp(self):
        p = mock.patch(
            "agentops_runtime.lifecycle_guard.operator_channel.load_signed_document",
            return_value={"ok": False, "detail": "no signed decision"})
        self.load = p.start()
        self.addCleanup(p.stop)

    def _signed(self, decision="APPROVE", action=None, head=HEAD):
        self.load.return_value = signed_payload(decision, action, head=head)

    def test_all_lifecycle_actions_block_during_wait(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td)
            for action in lifecycle_guard.LIFECYCLE_ACTIONS:
                out = lifecycle_guard.lifecycle_check(td, REPO, PR, HEAD, action)
                self.assertTrue(out["blocked"])
                self.assertEqual(out["state"], "WAITING_PO_AUTH")

    def test_delivery_failure_does_not_weaken_freeze(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td, delivered=False)
            self.assertTrue(lifecycle_guard.gate_applies(td, REPO, PR, HEAD))
            self.assertTrue(lifecycle_guard.lifecycle_check(
                td, REPO, PR, HEAD, "merge")["blocked"])

    def test_handwritten_bridge_po_decision_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td)
            self._write(td, "po_decision.json", {
                "repo": REPO, "pr": PR, "head": HEAD,
                "decision": "APPROVE", "lifecycle_action": "merge",
            })
            self.assertTrue(lifecycle_guard.waiting_for_po(td, REPO, PR, HEAD))
            self.assertTrue(lifecycle_guard.lifecycle_check(
                td, REPO, PR, HEAD, "merge")["blocked"])

    def test_generic_signed_approve_resumes_loop_but_not_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td)
            self._signed("APPROVE")
            self.assertFalse(lifecycle_guard.waiting_for_po(td, REPO, PR, HEAD))
            close = lifecycle_guard.lifecycle_check(td, REPO, PR, HEAD, "close")
            self.assertTrue(close["blocked"])
            self.assertEqual(close["state"], "PO_DECISION_RECEIVED")

    def test_action_specific_signed_approve_releases_only_that_action(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td)
            self._signed("APPROVE", "close")
            self.assertTrue(lifecycle_guard.lifecycle_check(
                td, REPO, PR, HEAD, "close")["ok"])
            self.assertTrue(lifecycle_guard.lifecycle_check(
                td, REPO, PR, HEAD, "merge")["blocked"])

    def test_non_approve_cannot_authorize_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td)
            self._signed("REJECT", "close")
            self.assertTrue(lifecycle_guard.lifecycle_check(
                td, REPO, PR, HEAD, "close")["blocked"])

    def test_stale_signed_decision_does_not_release_current_head(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td)
            self._signed("APPROVE", "close", head="0" * 40)
            self.assertTrue(lifecycle_guard.waiting_for_po(td, REPO, PR, HEAD))

    def test_remote_close_without_signed_action_approval_records_violation(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td)
            violation = lifecycle_guard.terminal_mutation_violation(
                td, REPO, PR, HEAD, "CLOSED")
            self.assertTrue(violation["violation"])
            self.assertEqual(violation["action"], "close")
            self.assertEqual(lifecycle_guard.read_violation(td)["head"], HEAD)
            self._signed("APPROVE", "close")
            again = lifecycle_guard.terminal_mutation_violation(
                td, REPO, PR, HEAD, "CLOSED")
            self.assertTrue(again["violation"])

    def test_prior_exact_signed_close_approval_prevents_violation(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td)
            self._signed("APPROVE", "close")
            self.assertIsNone(lifecycle_guard.terminal_mutation_violation(
                td, REPO, PR, HEAD, "CLOSED"))

    def test_active_manual_terminal_violation_needs_no_gate_file(self):
        with tempfile.TemporaryDirectory() as td:
            violation = lifecycle_guard.active_manual_terminal_violation(
                td, REPO, PR, HEAD, "CLOSED")
            self.assertTrue(violation["violation"])
            self.assertEqual(violation["action"], "close")
            self.assertIn("MANUAL task was still active", violation["detail"])

    def test_active_manual_terminal_with_exact_signed_action_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            self._signed("APPROVE", "close")
            self.assertIsNone(lifecycle_guard.active_manual_terminal_violation(
                td, REPO, PR, HEAD, "CLOSED"))


class TestDirectDecideLifecycle(GateMixin, unittest.TestCase):
    def _manual_spec(self):
        return TaskSpec("AGE-X", "MANUAL", "review approval", [])

    def test_direct_decide_closed_during_gate_is_not_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            self._gate(td)
            with mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                            return_value=td), \
                 mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                            return_value=self._manual_spec()), \
                 mock.patch("agentops_runtime.runtime_loop.linear_adapter.read_linear_issue",
                            return_value={"state_name": "In Progress", "state_type": "started"}), \
                 mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                            return_value=HEAD), \
                 mock.patch("agentops_runtime.runtime_loop.subprocess.run") as run, \
                 mock.patch("agentops_runtime.lifecycle_guard.operator_channel.load_signed_document",
                            return_value={"ok": False, "detail": "no decision"}), \
                 mock.patch("agentops_runtime.runtime_loop._loopx_refresh",
                            return_value={"ok": True}):
                run.return_value = mock.Mock(
                    returncode=0, stdout='{"state":"CLOSED"}', stderr="")
                out = runtime_loop.decide("AGE-X", REPO, PR)
            self.assertEqual(out["phase"], "BLOCKED")
            self.assertEqual(out["review_decision"], "LIFECYCLE_VIOLATION")
            self.assertTrue(out["lifecycle_violation"]["violation"])

    def test_direct_decide_closed_manual_without_gate_is_violation(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=self._manual_spec()), \
             mock.patch("agentops_runtime.runtime_loop.linear_adapter.read_linear_issue",
                        return_value={"state_name": "In Progress", "state_type": "started"}), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value=HEAD), \
             mock.patch("agentops_runtime.runtime_loop._pr_state",
                        return_value={"state": "CLOSED"}), \
             mock.patch("agentops_runtime.lifecycle_guard.operator_channel.load_signed_document",
                        return_value={"ok": False, "detail": "no decision"}), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh",
                        return_value={"ok": True}):
            out = runtime_loop.decide("AGE-X", REPO, PR)
        self.assertEqual(out["phase"], "BLOCKED")
        self.assertEqual(out["review_decision"], "LIFECYCLE_VIOLATION")

    def test_active_manual_signed_close_is_terminal_even_without_gate(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td), \
             mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=self._manual_spec()), \
             mock.patch("agentops_runtime.runtime_loop.linear_adapter.read_linear_issue",
                        return_value={"state_name": "In Progress", "state_type": "started"}), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head",
                        return_value=HEAD), \
             mock.patch("agentops_runtime.runtime_loop._pr_state",
                        return_value={"state": "CLOSED"}), \
             mock.patch("agentops_runtime.lifecycle_guard.operator_channel.load_signed_document",
                        return_value=signed_payload("APPROVE", "close")), \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh",
                        return_value={"ok": True}):
            out = runtime_loop.decide("AGE-X", REPO, PR)
        self.assertEqual(out["phase"], "TERMINAL")

    def test_completed_manual_task_can_be_terminal(self):
        with mock.patch("agentops_runtime.runtime_loop.spec_from_linear",
                        return_value=self._manual_spec()), \
             mock.patch("agentops_runtime.runtime_loop.linear_adapter.read_linear_issue",
                        return_value={"state_name": "Done", "state_type": "completed"}), \
             mock.patch("agentops_runtime.runtime_loop.read_pr_head") as head, \
             mock.patch("agentops_runtime.runtime_loop._loopx_refresh",
                        return_value={"ok": True}):
            out = runtime_loop.decide("AGE-X", REPO, PR)
        self.assertEqual(out["phase"], "TERMINAL")
        head.assert_not_called()

    def test_runtime_authenticated_po_decision_ignores_bridge_file(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "po_decision.json", {
                "repo": REPO, "pr": PR, "head": HEAD, "decision": "APPROVE"})
            with mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                            return_value=td), \
                 mock.patch("agentops_runtime.lifecycle_guard.operator_channel.load_signed_document",
                            return_value={"ok": False, "detail": "unsigned"}):
                self.assertIsNone(runtime_loop._authenticated_po_decision(
                    REPO, PR, HEAD))

    def test_runtime_authenticated_po_decision_accepts_verified_external_decision(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("agentops_runtime.runtime_loop._bridge_dir",
                        return_value=td), \
             mock.patch("agentops_runtime.lifecycle_guard.operator_channel.load_signed_document",
                        return_value=signed_payload("APPROVE")):
            self.assertEqual(runtime_loop._authenticated_po_decision(
                REPO, PR, HEAD), "APPROVE")


class TestWatcherManualGateLifecycle(unittest.TestCase):
    def test_watcher_terminal_helper_has_no_remote_lifecycle_authority(self):
        watcher = ControlWatcher("AGE-X", REPO, PR, interval=5)
        self.assertFalse(watcher._terminal())

    def test_watcher_decide_first_keeps_lifecycle_violation_alive(self):
        watcher = ControlWatcher("AGE-X", REPO, PR, interval=5)
        violation = {"violation": True, "action": "close", "remote_state": "CLOSED"}
        outcomes = [
            {"phase": "BLOCKED", "review_decision": "LIFECYCLE_VIOLATION",
             "lifecycle_violation": violation, "loopx": {"ok": True}},
            {"phase": "TERMINAL", "review_decision": "INCOMPLETE",
             "loopx": {"ok": True}},
        ]
        with mock.patch("agentops_runtime.controller.time.sleep"), \
             mock.patch("agentops_runtime.controller.decide", side_effect=outcomes) as step:
            self.assertTrue(watcher.run_forever())
        self.assertEqual(step.call_count, 2)


class TestNoBuilderPOCLI(unittest.TestCase):
    def test_po_decision_command_is_removed(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["po-decision", "--repo", REPO, "--pr", PR,
                               "--head", HEAD, "--decision", "APPROVE"])


if __name__ == "__main__":
    unittest.main()
