import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import manual_approval
from governloop_runtime.__main__ import build_parser


def scope_block(paths=None):
    outside = paths or ["notes/private.txt"]
    return {
        "name": "worktree_scope",
        "status": "BLOCKED",
        "detail": "uncommitted paths outside operator-bound scope",
        "data": {"outside_paths": outside, "changed_paths": ["src/app.py", *outside]},
    }


class ManualApprovalTests(unittest.TestCase):
    def test_request_id_is_deterministic_and_content_bound(self):
        first = manual_approval.request_id("AGE-X", scope_block())
        second = manual_approval.request_id("AGE-X", scope_block())
        changed = manual_approval.request_id("AGE-X", scope_block(["other.txt"]))
        other_task = manual_approval.request_id("AGE-Y", scope_block())
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertNotEqual(first, other_task)

    def test_only_exact_worktree_scope_exception_is_approvable(self):
        self.assertTrue(manual_approval.is_approvable(scope_block()))
        hard = {"name": "positive_authority", "status": "BLOCKED",
                "detail": "authority missing", "data": {"outside_paths": ["x"]}}
        unreadable = {"name": "worktree_scope", "status": "BLOCKED",
                      "detail": "cannot determine complete worktree state: git failed",
                      "data": {"outside_paths": ["x"]}}
        self.assertFalse(manual_approval.is_approvable(hard))
        self.assertFalse(manual_approval.is_approvable(unreadable))

    def test_external_signed_approval_requires_exact_task_request_and_status(self):
        rid = "a" * 64
        good = {"schema": manual_approval.SCHEMA, "task_id": "AGE-X",
                "request_id": rid, "status": "APPROVED", "approval_id": "po-1"}
        with mock.patch("governloop_runtime.manual_approval.approval_path",
                        return_value=mock.Mock()), \
             mock.patch("governloop_runtime.manual_approval.operator_channel.load_signed_document",
                        return_value={"ok": True, "payload": good, "detail": "verified"}):
            self.assertTrue(manual_approval.verify_approval("AGE-X", rid)["ok"])

        for patch in ({"task_id": "AGE-Y"}, {"request_id": "b" * 64}, {"status": "REJECTED"}):
            payload = {**good, **patch}
            with mock.patch("governloop_runtime.manual_approval.approval_path",
                            return_value=mock.Mock()), \
                 mock.patch("governloop_runtime.manual_approval.operator_channel.load_signed_document",
                            return_value={"ok": True, "payload": payload, "detail": "verified"}):
                self.assertFalse(manual_approval.verify_approval("AGE-X", rid)["ok"])

    def test_builder_owned_or_unverified_evidence_cannot_release(self):
        check = scope_block()
        with mock.patch("governloop_runtime.manual_approval.operator_channel.control_root",
                        return_value=None):
            checks, requests = manual_approval.apply_to_checks("AGE-X", [check])
        self.assertEqual(checks[0]["status"], "BLOCKED")
        self.assertEqual(len(requests), 1)

    def test_exact_verified_scope_approval_releases_only_that_check(self):
        scope = scope_block()
        hard = {"name": "positive_authority", "status": "BLOCKED",
                "detail": "authority missing"}
        with mock.patch("governloop_runtime.manual_approval.verify_approval",
                        return_value={"ok": True, "approval_id": "po-1"}):
            checks, requests = manual_approval.apply_to_checks("AGE-X", [scope, hard])
        self.assertEqual(checks[0]["status"], "MANUALLY_APPROVED")
        self.assertEqual(checks[1]["status"], "BLOCKED")
        self.assertEqual(requests, [])

    def test_no_builder_approval_minting_cli_exists(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["approve-request"])


if __name__ == "__main__":
    unittest.main()
