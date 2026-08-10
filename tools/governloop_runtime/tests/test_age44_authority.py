import json
import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import _compat, authority, operator_channel
from governloop_runtime.__main__ import build_parser

BASE = "0123456789abcdef0123456789abcdef01234567"
PAYLOAD = {
    "schema": "governloop-authority-v2",
    "authority_id": "external-auth-1",
    "task_id": "AGE-X",
    "repository": "owner/repo",
    "branch": "feat/age-x",
    "baseline_sha": BASE,
    "allowed_paths": ["src/", "tests/"],
    "allowed_operations": ["fix", "continue", "complete"],
    "trusted_reviewers": ["trusted-reviewer"],
}


class TestVerifyOnlyAuthority(unittest.TestCase):
    def test_runtime_has_no_authority_minting_api(self):
        self.assertFalse(hasattr(authority, "bind_authority"))
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["bind-authority"])

    def test_governloop_home_cannot_redirect_control_root(self):
        fake_home = "/tmp/builder-chosen-home"
        with mock.patch.dict(os.environ, {"GOVERNLOOP_HOME": fake_home}, clear=True), \
             mock.patch("governloop_runtime.operator_channel.os_account_home",
                        return_value=operator_channel.Path("/real/os/home")):
            self.assertEqual(
                operator_channel.control_root(),
                operator_channel.Path("/real/os/home/.governloop/control"))
            self.assertNotIn(fake_home, str(operator_channel.control_root()))

    def test_same_uid_control_document_is_not_protected(self):
        path = mock.Mock()
        path.exists.return_value = True
        path.is_file.return_value = True
        parent = mock.Mock()
        parent.exists.return_value = True
        parent.is_dir.return_value = True
        path.parent = parent
        with mock.patch("governloop_runtime.operator_channel._owned_by_runtime",
                        return_value=True):
            self.assertFalse(operator_channel.protected_control_path(path))

    def test_verified_external_document_is_accepted(self):
        with mock.patch("governloop_runtime.authority.authority_path",
                        return_value=operator_channel.Path("/operator/AGE-X.json")), \
             mock.patch("governloop_runtime.authority.operator_channel.load_signed_document",
                        return_value={"ok": True, "payload": dict(PAYLOAD),
                                      "detail": "verified"}):
            out = authority.verify_authority("AGE-X", "owner/repo")
        self.assertTrue(out["ok"])
        self.assertEqual(out["payload"]["trusted_reviewers"], ["trusted-reviewer"])

    def test_unsigned_or_writable_external_document_fails_closed(self):
        with mock.patch("governloop_runtime.authority.authority_path",
                        return_value=operator_channel.Path("/operator/AGE-X.json")), \
             mock.patch("governloop_runtime.authority.operator_channel.load_signed_document",
                        return_value={"ok": False,
                                      "detail": "signed control document absent or writable by runtime uid"}):
            out = authority.verify_authority("AGE-X", "owner/repo")
        self.assertFalse(out["ok"])
        self.assertIn("writable", out["detail"])

    def test_wrong_repo_fails_closed_after_valid_signature(self):
        with mock.patch("governloop_runtime.authority.authority_path",
                        return_value=operator_channel.Path("/operator/AGE-X.json")), \
             mock.patch("governloop_runtime.authority.operator_channel.load_signed_document",
                        return_value={"ok": True, "payload": dict(PAYLOAD),
                                      "detail": "verified"}):
            out = authority.verify_authority("AGE-X", "other/repo")
        self.assertFalse(out["ok"])
        self.assertIn("repository binding mismatch", out["detail"])

    def test_raw_process_authority_is_ignored_when_external_channel_missing(self):
        raw = {
            "GOVERNLOOP_SCOPE_REPOSITORY": "owner/repo",
            "GOVERNLOOP_AUTHORIZED_BRANCH": "self-chosen",
            "GOVERNLOOP_BASELINE_SHA": BASE,
            "GOVERNLOOP_ALLOWED_PATHS": ".",
            "GOVERNLOOP_AUTHORIZED_OPERATIONS": "fix,continue,complete",
            "GOVERNLOOP_TRUSTED_REVIEWERS": "builder-self",
            "AGENTOPS_SCOPE_REPOSITORY": "owner/repo",
            "AGENTOPS_AUTHORIZED_BRANCH": "builder-legacy",
            "AGENTOPS_TRUSTED_REVIEWERS": "builder-self-legacy",
        }
        with mock.patch.dict(os.environ, raw, clear=True), \
             mock.patch("governloop_runtime.authority.authority_path",
                        return_value=operator_channel.Path("/operator/AGE-X.json")), \
             mock.patch("governloop_runtime.authority.operator_channel.load_signed_document",
                        return_value={"ok": False, "detail": "no external authority"}):
            out = _compat.configure_process("AGE-X", "owner/repo")
        self.assertFalse(out["ok"])
        self.assertIn("GOVERNLOOP_AUTHORIZED_BRANCH",
                      out["ignored_process_authority_fields"])
        self.assertIn("AGENTOPS_AUTHORIZED_BRANCH",
                      out["ignored_process_authority_fields"])

    def test_verified_authority_projects_compat_values(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("governloop_runtime.authority.verify_authority",
                        return_value={"ok": True, "status": "READY",
                                      "authority_id": "external-auth-1",
                                      "payload": dict(PAYLOAD), "detail": "verified"}):
            out = authority.apply_verified_authority("AGE-X", "owner/repo")
            self.assertTrue(out["ok"])
            self.assertEqual(os.environ["GOVERNLOOP_AUTHORIZED_BRANCH"],
                             "feat/age-x")
            self.assertEqual(os.environ["GOVERNLOOP_TRUSTED_REVIEWERS"],
                             "trusted-reviewer")


class TestAuthorityCLI(unittest.TestCase):
    def test_only_read_only_authority_check_is_exposed(self):
        parser = build_parser()
        args = parser.parse_args([
            "authority-check", "--task-id", "AGE-X", "--repo", "owner/repo"])
        self.assertEqual(args.command, "authority-check")


if __name__ == "__main__":
    unittest.main()
