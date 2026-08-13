import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from governloop_runtime import external_path


class ExternalPathAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.root = self.base / "root"
        self.root.mkdir()
        self.sibling = self.base / "sibling"
        self.sibling.mkdir()
        now = datetime.now(timezone.utc)
        self.payload = {
            "schema": external_path.SCHEMA,
            "authority_id": "ext-1",
            "scope_kind": "external_path",
            "task_id": "GENERIC-TEST",
            "subject_id": external_path.current_subject_id(),
            "allowed_root": str(self.root),
            "allowed_operations": ["read", "preserve-copy"],
            "issued_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "issuer_key_id": "operator-1",
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def verify(self, target, operation="read", payload=None):
        with patch("governloop_runtime.external_path.authority_path", return_value=Path("/protected/ext.json")), \
             patch("governloop_runtime.external_path.operator_channel.load_signed_document", return_value={"ok": True, "payload": payload or self.payload}), \
             patch("governloop_runtime.external_path._revoked", return_value=False):
            return external_path.verify_external_authority("GENERIC-TEST", operation, str(target))

    def test_valid_external_path(self):
        self.assertTrue(self.verify(self.root / "evidence.txt").get("ok"))

    def test_sibling_escape_blocks(self):
        self.assertFalse(self.verify(self.sibling / "secret.txt").get("ok"))

    def test_traversal_blocks(self):
        self.assertFalse(self.verify(str(self.root / ".." / "sibling" / "secret.txt")).get("ok"))

    def test_symlink_escape_blocks(self):
        link = self.root / "outside"
        link.symlink_to(self.sibling, target_is_directory=True)
        self.assertFalse(self.verify(link / "secret.txt").get("ok"))

    def test_wrong_operation_blocks(self):
        self.assertFalse(self.verify(self.root / "file.txt", operation="move").get("ok"))

    def test_wrong_task_blocks(self):
        payload = dict(self.payload)
        payload["task_id"] = "OTHER"
        self.assertFalse(self.verify(self.root / "file.txt", payload=payload).get("ok"))

    def test_wrong_subject_blocks(self):
        payload = dict(self.payload)
        payload["subject_id"] = "local-os:uid:999999"
        self.assertFalse(self.verify(self.root / "file.txt", payload=payload).get("ok"))

    def test_expired_authority_blocks(self):
        payload = dict(self.payload)
        payload["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.assertFalse(self.verify(self.root / "file.txt", payload=payload).get("ok"))

    def test_revoked_authority_blocks(self):
        with patch("governloop_runtime.external_path.authority_path", return_value=Path("/protected/ext.json")), \
             patch("governloop_runtime.external_path.operator_channel.load_signed_document", return_value={"ok": True, "payload": self.payload}), \
             patch("governloop_runtime.external_path._revoked", return_value=True):
            self.assertFalse(external_path.verify_external_authority("GENERIC-TEST", "read", str(self.root / "file.txt")).get("ok"))


if __name__ == "__main__":
    unittest.main()
