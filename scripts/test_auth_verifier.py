import unittest
import time
from auth_verifier import AuthVerifier, AuthContext, ActionRequest

class TestAuthVerifier(unittest.TestCase):
    def setUp(self):
        self.verifier = AuthVerifier()
        self.valid_expiry = time.time() + 3600
        
        self.base_auth = AuthContext(
            provenance="PO",
            request_id="req-123",
            repository="owner/repo",
            branch="feature/AGE-5",
            base_sha="abcdef1",
            target_sha="abcdef2",
            allowed_paths=["docs/"],
            allowed_action_types=["commit", "push"],
            expiry=self.valid_expiry,
            revoked=False,
            is_one_time=True,
            consumed=False
        )

        self.valid_action = ActionRequest(
            request_id="req-123",
            repository="owner/repo",
            branch="feature/AGE-5",
            base_sha="abcdef1",
            target_sha="abcdef2",
            target_paths=["docs/governance.md"],
            action_type="commit"
        )

    def test_valid_authorization(self):
        self.verifier.grant_authorization(self.base_auth)
        self.assertTrue(self.verifier.verify(self.valid_action))
        
        # Test one-time consumption
        self.assertFalse(self.verifier.verify(self.valid_action), "Should fail if one-time auth is already consumed")

    def test_fail_missing_auth(self):
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_invalid_provenance(self):
        self.base_auth.provenance = "Agent"
        self.verifier.grant_authorization(self.base_auth)
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_revoked(self):
        self.base_auth.revoked = True
        self.verifier.grant_authorization(self.base_auth)
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_expired(self):
        self.base_auth.expiry = time.time() - 100
        self.verifier.grant_authorization(self.base_auth)
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_repo_mismatch(self):
        self.verifier.grant_authorization(self.base_auth)
        action = self.valid_action
        action.repository = "owner/other-repo"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_branch_mismatch(self):
        self.verifier.grant_authorization(self.base_auth)
        action = self.valid_action
        action.branch = "main"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_sha_mismatch(self):
        self.verifier.grant_authorization(self.base_auth)
        action = self.valid_action
        action.base_sha = "wrong"
        self.assertFalse(self.verifier.verify(action))
        
        action.base_sha = "abcdef1"
        action.target_sha = "wrong"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_action_type_mismatch(self):
        # Inferring Ready/Merge from commit is invalid
        self.verifier.grant_authorization(self.base_auth)
        action = self.valid_action
        action.action_type = "merge"
        self.assertFalse(self.verifier.verify(action))

    def test_fail_scope_mismatch(self):
        self.verifier.grant_authorization(self.base_auth)
        action = self.valid_action
        action.target_paths = ["src/main.py"]
        self.assertFalse(self.verifier.verify(action))

if __name__ == '__main__':
    unittest.main()
