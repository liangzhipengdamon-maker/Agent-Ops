import unittest
import time
import os
from auth_verifier import AuthVerifier, AuthContext, ActionRequest

class TestAuthVerifier(unittest.TestCase):
    def setUp(self):
        self.verifier = AuthVerifier()
        self.valid_expiry = time.time() + 3600
        
        self.base_auth = AuthContext(
            trusted_signature="valid_po_sig_xyz123",
            request_id="req-123",
            task_id="task-456",
            repository="owner/repo",
            branch="feature/AGE-5",
            base_sha="abcdef1",
            target_sha="abcdef2",
            allowed_paths=["docs/"],
            allowed_operations=["write_file"],
            allowed_action_types=["commit", "push"],
            expiry=self.valid_expiry,
            revoked=False,
            is_one_time=True,
            consumed=False
        )

        self.valid_action = ActionRequest(
            request_id="req-123",
            task_id="task-456",
            repository="owner/repo",
            branch="feature/AGE-5",
            base_sha="abcdef1",
            target_sha="abcdef2",
            target_paths=["docs/governance.md"],
            operation="write_file",
            action_type="commit"
        )

    def test_valid_authorization_and_consume(self):
        self.verifier.grant_authorization(self.base_auth)
        self.assertTrue(self.verifier.verify(self.valid_action))
        
        # Test explicit one-time consumption
        self.assertTrue(self.verifier.consume("req-123"))
        self.assertFalse(self.verifier.verify(self.valid_action), "Should fail if one-time auth is already consumed")

    def test_fail_duplicate_grant(self):
        self.verifier.grant_authorization(self.base_auth)
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(self.base_auth)

    def test_fail_invalid_provenance(self):
        self.base_auth.trusted_signature = "invalid_sig_agent"
        self.verifier.grant_authorization(self.base_auth)
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_task_id_mismatch(self):
        self.verifier.grant_authorization(self.base_auth)
        action = self.valid_action
        action.task_id = "task-789"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_path_traversal(self):
        self.verifier.grant_authorization(self.base_auth)
        action = self.valid_action
        # Attempt to bypass via ../
        action.target_paths = ["docs/../src/secret.py"]
        self.assertFalse(self.verifier.verify(action))

        action.target_paths = ["/etc/passwd"]
        self.assertFalse(self.verifier.verify(action))

    def test_fail_operation_mismatch(self):
        self.verifier.grant_authorization(self.base_auth)
        action = self.valid_action
        action.operation = "delete_file"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_action_type_mismatch(self):
        self.verifier.grant_authorization(self.base_auth)
        action = self.valid_action
        action.action_type = "merge"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_missing_auth(self):
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_revoked(self):
        self.base_auth.revoked = True
        self.verifier.grant_authorization(self.base_auth)
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_expired(self):
        self.base_auth.expiry = time.time() - 100
        self.verifier.grant_authorization(self.base_auth)
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_repo_branch_sha_mismatch(self):
        self.verifier.grant_authorization(self.base_auth)
        action1 = ActionRequest(**{**self.valid_action.__dict__, "repository": "owner/other-repo"})
        self.assertFalse(self.verifier.verify(action1))

        action2 = ActionRequest(**{**self.valid_action.__dict__, "branch": "main"})
        self.assertFalse(self.verifier.verify(action2))

        action3 = ActionRequest(**{**self.valid_action.__dict__, "base_sha": "wrong"})
        self.assertFalse(self.verifier.verify(action3))
        
        action4 = ActionRequest(**{**self.valid_action.__dict__, "target_sha": "wrong"})
        self.assertFalse(self.verifier.verify(action4))


if __name__ == '__main__':
    unittest.main()
