import unittest
import time
import threading
from auth_verifier import (
    ActionRequest,
    AuthContext,
    AuthVerifier,
    TrustedAuthorizationProvider,
    VerifiedAssertion,
)


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
            consumed=False,
        )

        # Real provider-issued assertion — the only path into the trust boundary.
        self.valid_assertion = self.provider.issue_assertion(self.base_auth)

        self.valid_action = ActionRequest(
            request_id="req-123",
            task_id="task-456",
            repository="owner/repo",
            branch="feature/AGE-5",
            base_sha="abcdef1",
            target_sha="abcdef2",
            target_paths=["docs/governance.md"],
            operation="write_file",
            action_type="commit",
        )

    # ------------------------------------------------------------------
    # A. Trusted provenance — object-identity / provider-held registry
    # ------------------------------------------------------------------

    def test_provider_issued_assertion_accepted(self):
        """An assertion minted by the configured provider must be accepted."""
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertIn("req-123", self.verifier.auth_store)
        self.assertTrue(self.verifier.verify(self.valid_action))

    def test_fail_manually_constructed_assertion(self):
        """VerifiedAssertion constructed outside issue_assertion must fail closed.

        There is no caller-visible token string to guess or default to: the
        only way into the trust boundary is ``TrustedAuthorizationProvider.
        issue_assertion``, which registers the assertion in the provider's
        private registry.
        """
        forged = VerifiedAssertion(_auth=self.base_auth, _provider=self.provider)
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(forged)
        self.assertNotIn("req-123", self.verifier.auth_store)

    def test_fail_copied_assertion_fields(self):
        """Field-by-field copy of a legitimate assertion must fail closed.

        Even when the forged object references the exact same provider
        instance, it is not in the provider's issuance registry and therefore
        has no provenance.
        """
        # Sanity: the legitimate path works first.
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertTrue(self.verifier.verify(self.valid_action))

        # Forge a clone by copying the only two fields of a legitimate
        # assertion. Object identity differs, so the forgery is not in the
        # provider's registry.
        forged = VerifiedAssertion(
            _auth=self.valid_assertion._auth,
            _provider=self.valid_assertion._provider,
        )
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(forged)

    def test_fail_assertion_from_unrelated_provider(self):
        """An assertion issued by a different provider must fail closed on our verifier."""
        other_provider = TrustedAuthorizationProvider()
        other_auth = AuthContext(
            request_id="req-other",
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
            is_one_time=False,
            consumed=False,
        )
        other_assertion = other_provider.issue_assertion(other_auth)
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(other_assertion)
        self.assertNotIn("req-other", self.verifier.auth_store)

    # ------------------------------------------------------------------
    # E. duplicate / conflicting authorization — fail closed
    # ------------------------------------------------------------------

    def test_fail_duplicate_grant(self):
        self.verifier.grant_authorization(self.valid_assertion)
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(self.valid_assertion)

    # ------------------------------------------------------------------
    # B. task / mission binding
    # ------------------------------------------------------------------

    def test_fail_task_id_mismatch(self):
        self.verifier.grant_authorization(self.valid_assertion)
        action = self.valid_action
        action.task_id = "task-789"
        self.assertFalse(self.verifier.verify(action))

    # ------------------------------------------------------------------
    # D. path scope — exact / prefix bounded, no wildcards, no traversal
    # ------------------------------------------------------------------

    def test_fail_wildcard_no_longer_supported(self):
        # Setting '*' as the allowed path should literally mean a directory
        # named '*', since wildcard logic was removed. It cannot authorize
        # any other path.
        auth = self.base_auth
        auth.request_id = "req-999"
        auth.allowed_paths = ["*"]
        assertion = self.provider.issue_assertion(auth)
        self.verifier.grant_authorization(assertion)

        action = self.valid_action
        action.request_id = "req-999"
        action.target_paths = ["src/main.py"]
        # Will fail because "*" is treated literally and does not match
        # "src/main.py".
        self.assertFalse(self.verifier.verify(action))

    def test_fail_path_traversal(self):
        self.verifier.grant_authorization(self.valid_assertion)
        action = self.valid_action
        # Attempt to bypass via ../
        action.target_paths = ["docs/../src/secret.py"]
        self.assertFalse(self.verifier.verify(action))

        # Attempt to bypass via absolute path
        action.target_paths = ["/etc/passwd"]
        self.assertFalse(self.verifier.verify(action))

    # ------------------------------------------------------------------
    # C. operation / action_type separation
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # General negative coverage
    # ------------------------------------------------------------------

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
        action1 = ActionRequest(
            **{**self.valid_action.__dict__, "repository": "owner/other-repo"}
        )
        self.assertFalse(self.verifier.verify(action1))

        action2 = ActionRequest(
            **{**self.valid_action.__dict__, "branch": "main"}
        )
        self.assertFalse(self.verifier.verify(action2))

        action3 = ActionRequest(
            **{**self.valid_action.__dict__, "base_sha": "wrong"}
        )
        self.assertFalse(self.verifier.verify(action3))

        action4 = ActionRequest(
            **{**self.valid_action.__dict__, "target_sha": "wrong"}
        )
        self.assertFalse(self.verifier.verify(action4))

    # ------------------------------------------------------------------
    # F. one-time authorization — verify vs consume separated
    # ------------------------------------------------------------------

    def test_valid_authorization_and_consume(self):
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertTrue(self.verifier.verify(self.valid_action))

        # Test explicit one-time consumption
        self.assertTrue(self.verifier.consume("req-123"))
        self.assertFalse(
            self.verifier.verify(self.valid_action),
            "Should fail if one-time auth is already consumed",
        )

    def test_concurrent_consume(self):
        # Test that consume is transaction-safe via locking
        self.verifier.grant_authorization(self.valid_assertion)

        successes = []
        result_lock = threading.Lock()

        def concurrent_task():
            if self.verifier.consume("req-123"):
                with result_lock:
                    successes.append(True)

        threads = [threading.Thread(target=concurrent_task) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Only exactly one thread should have successfully consumed it
        self.assertEqual(len(successes), 1)


if __name__ == "__main__":
    unittest.main()