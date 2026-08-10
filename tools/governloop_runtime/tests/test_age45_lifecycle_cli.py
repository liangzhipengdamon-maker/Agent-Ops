import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime.__main__ import build_parser
from agentops_runtime import lifecycle_guard

HEAD = "0123456789abcdef0123456789abcdef01234567"


class TestLifecycleDecisionCLI(unittest.TestCase):
    def test_po_decision_command_is_not_exposed(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "po-decision", "--repo", "owner/repo", "--pr", "42",
                "--head", HEAD, "--decision", "APPROVE",
            ])

    def test_generic_verified_approve_has_no_lifecycle_authority(self):
        verified = {
            "ok": True,
            "payload": {
                "schema": lifecycle_guard.PO_SCHEMA,
                "repo": "owner/repo",
                "pr": "42",
                "head": HEAD,
                "decision": "APPROVE",
            },
            "detail": "verified",
        }
        with mock.patch(
                "agentops_runtime.lifecycle_guard.operator_channel.load_signed_document",
                return_value=verified):
            decision = lifecycle_guard.read_po_decision(
                ".agent-bridge", "owner/repo", "42", HEAD)
            self.assertEqual(decision["decision"], "APPROVE")
            self.assertFalse(lifecycle_guard.lifecycle_action_authorized(
                ".agent-bridge", "owner/repo", "42", HEAD, "close"))

    def test_action_specific_verified_approve_binds_only_exact_action(self):
        verified = {
            "ok": True,
            "payload": {
                "schema": lifecycle_guard.PO_SCHEMA,
                "repo": "owner/repo",
                "pr": "42",
                "head": HEAD,
                "decision": "APPROVE",
                "lifecycle_action": "close",
            },
            "detail": "verified",
        }
        with mock.patch(
                "agentops_runtime.lifecycle_guard.operator_channel.load_signed_document",
                return_value=verified):
            self.assertTrue(lifecycle_guard.lifecycle_action_authorized(
                ".agent-bridge", "owner/repo", "42", HEAD, "close"))
            self.assertFalse(lifecycle_guard.lifecycle_action_authorized(
                ".agent-bridge", "owner/repo", "42", HEAD, "merge"))


if __name__ == "__main__":
    unittest.main()
