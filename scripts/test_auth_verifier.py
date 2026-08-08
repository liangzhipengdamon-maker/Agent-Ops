import unittest
import time
import os
import threading
from auth_verifier import AuthVerifier, AuthContext, ActionRequest, TrustedAuthorizationProvider, VerifiedAssertion

class TestAuthVerifier(unittest.TestCase):
    def setUp(self):
        self.provider = TrustedAuthorizationProvider()
        self.verifier = AuthVerifier(self.provider)
        self.valid_expiry = time.time() + 3600
        
        self.base_auth = AuthContext(
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

        self.valid_assertion = self.provider.issue_assertion(self.base_auth, "VALID_PO_SIG_xyz123")

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
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertTrue(self.verifier.verify(self.valid_action))
        
        # Test explicit one-time consumption
        self.assertTrue(self.verifier.consume("req-123"))
        self.assertFalse(self.verifier.verify(self.valid_action), "Should fail if one-time auth is already consumed")

    def test_concurrent_consume(self):
        # Test that consume is transaction-safe via locking
        self.verifier.grant_authorization(self.valid_assertion)
        
        successes = []
        def concurrent_task():
            if self.verifier.consume("req-123"):
                successes.append(True)
                
        threads = [threading.Thread(target=concurrent_task) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Only exactly one thread should have successfully consumed it
        self.assertEqual(len(successes), 1)

    def test_fail_duplicate_grant(self):
        self.verifier.grant_authorization(self.valid_assertion)
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(self.valid_assertion)

    def test_fail_invalid_provenance_signature(self):
        with self.assertRaises(ValueError):
            # Forging a signature throws an error before it can even become an assertion
            self.provider.issue_assertion(self.base_auth, "invalid_sig_agent")

    def test_fail_untrusted_assertion(self):
        # Even if we somehow mock a VerifiedAssertion, if it doesn't have the right token it fails closed
        fake_assertion = VerifiedAssertion(_auth=self.base_auth, _issuer_token="fake_token")
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(fake_assertion)

    def test_fail_task_id_mismatch(self):
        self.verifier.grant_authorization(self.valid_assertion)
        action = self.valid_action
        action.task_id = "task-789"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_wildcard_no_longer_supported(self):
        # Setting '*' as allowed path should literally mean a directory named '*'
        # since wildcard logic was removed
        auth = self.base_auth
        auth.request_id = "req-999"
        auth.allowed_paths = ["*"]
        assertion = self.provider.issue_assertion(auth, "VALID_PO_SIG_xxx")
        self.verifier.grant_authorization(assertion)
        
        action = self.valid_action
        action.request_id = "req-999"
        action.target_paths = ["src/main.py"]
        # Will fail because "*" is treated literally and does not match "src/main.py"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_path_traversal(self):
        self.verifier.grant_authorization(self.valid_assertion)
        action = self.valid_action
        # Attempt to bypass via ../
        action.target_paths = ["docs/../src/secret.py"]
        self.assertFalse(self.verifier.verify(action))

        action.target_paths = ["/etc/passwd"]
        self.assertFalse(self.verifier.verify(action))

    def test_fail_operation_mismatch(self):
        self.verifier.grant_authorization(self.valid_assertion)
        action = self.valid_action
        action.operation = "delete_file"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_action_type_mismatch(self):
        self.verifier.grant_authorization(self.valid_assertion)
        action = self.valid_action
        action.action_type = "merge"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_missing_auth(self):
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_revoked(self):
        self.base_auth.revoked = True
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_expired(self):
        self.base_auth.expiry = time.time() - 100
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_repo_branch_sha_mismatch(self):
        self.verifier.grant_authorization(self.valid_assertion)
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
