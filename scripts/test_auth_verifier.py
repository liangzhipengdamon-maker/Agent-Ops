import unittest
import time
import threading
from dataclasses import FrozenInstanceError
from auth_verifier import (
    ActionRequest,
    AuthContext,
    TrustedAuthorizationProvider,
    VerifiedAssertion,
)


def make_auth(**overrides) -> AuthContext:
    """Build an AuthContext for tests. Pass overrides to vary one field."""
    base = dict(
        request_id="req-123",
        task_id="task-456",
        repository="owner/repo",
        branch="feature/AGE-5",
        base_sha="abcdef1",
        target_sha="abcdef2",
        allowed_paths=("docs/",),
        allowed_operations=("write_file",),
        allowed_action_types=("commit", "push"),
        expiry=time.time() + 3600,
        revoked=False,
        is_one_time=True,
    )
    base.update(overrides)
    return AuthContext(**base)


class TestAuthVerifier(unittest.TestCase):
    def setUp(self):
        self.provider = TrustedAuthorizationProvider()
        # The verifier is created via the provider but does NOT hold a
        # reference back to it: no public path to minting.
        self.verifier = self.provider.create_verifier()

        self.base_auth = make_auth()

        # Legitimate issuance through the private trusted ingress (_mint).
        # This is the trusted PO channel in the reference model.
        self.valid_assertion = self.provider._mint(self.base_auth)

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
    # A. Issuer-side trust boundary — single-step payload-bound issuance
    # ------------------------------------------------------------------

    def test_legitimate_trusted_fixture_passes(self):
        """A legitimately issued trusted object (via the private trusted ingress) verifies normally."""
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertTrue(self.verifier.verify(self.valid_action))

    def test_fail_arbitrary_auth_cannot_be_authorized_via_public_api(self):
        """No public verifier/provider API can turn an arbitrary AuthContext into a trusted authorization."""
        arbitrary_auth = make_auth(
            request_id="req-evil",
            task_id="task-evil",
            branch="main",
            allowed_operations=("delete_file",),
            allowed_action_types=("deploy",),
        )

        # 1. The verifier exposes no reference to the provider (no mint surface).
        self.assertFalse(
            hasattr(self.verifier, "trusted_provider"),
            "AuthVerifier must not expose the provider",
        )
        for name in ("issue_assertion", "mint", "create_assertion", "sign"):
            self.assertFalse(
                hasattr(self.verifier, name),
                f"AuthVerifier must not expose a mint-like attribute {name!r}",
            )

        # 2. grant_authorization cannot accept a raw AuthContext.
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(arbitrary_auth)

        # 3. grant_authorization cannot accept a manually constructed object,
        #    even one carrying the arbitrary AuthContext and a provider ref.
        forged = VerifiedAssertion(_auth=arbitrary_auth, _provider=self.provider)
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(forged)

        # 4. verify() for the arbitrary context is never authorized.
        arbitrary_action = ActionRequest(
            request_id="req-evil",
            task_id="task-evil",
            repository="owner/repo",
            branch="main",
            base_sha="abcdef1",
            target_sha="abcdef2",
            target_paths=["docs/x.md"],
            operation="write_file",
            action_type="commit",
        )
        self.assertFalse(self.verifier.verify(arbitrary_action))

    def test_fail_assertion_for_a_cannot_authorize_b(self):
        """A trusted object minted for Auth A cannot be used to authorize Auth B."""
        auth_b = make_auth(request_id="req-B", task_id="task-B")
        assertion_a = self.valid_assertion  # bound to Auth A (req-123)
        self.verifier.grant_authorization(assertion_a)

        # An action for B must not be authorized by A's trusted object.
        action_b = ActionRequest(
            request_id="req-B",
            task_id="task-B",
            repository="owner/repo",
            branch="feature/AGE-5",
            base_sha="abcdef1",
            target_sha="abcdef2",
            target_paths=["docs/x.md"],
            operation="write_file",
            action_type="commit",
        )
        self.assertFalse(self.verifier.verify(action_b))

        # Rebinding A's trusted object to B's payload is rejected: the object
        # is immutable after issuance.
        with self.assertRaises(AttributeError):
            assertion_a._auth = auth_b  # type: ignore[misc]

        # A forged object carrying B's payload is not in the registry.
        forged = VerifiedAssertion(_auth=auth_b, _provider=self.provider)
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(forged)

    def test_fail_payload_modification_after_issuance(self):
        """Payload cannot be replaced or modified after trusted issuance."""
        assertion = self.provider._mint(self.base_auth)
        self.verifier.grant_authorization(assertion)
        self.assertTrue(self.verifier.verify(self.valid_action))

        # Replace the whole payload object -> object is immutable.
        other_auth = make_auth(request_id="req-other")
        with self.assertRaises(AttributeError):
            assertion._auth = other_auth  # type: ignore[misc]

        # Mutate a payload field -> AuthContext is frozen.
        with self.assertRaises(FrozenInstanceError):
            assertion._auth.revoked = True  # type: ignore[misc]

        # Replace a collection payload field -> AuthContext is frozen.
        with self.assertRaises(FrozenInstanceError):
            assertion._auth.allowed_paths = ("src/",)  # type: ignore[misc]

        # The verifier still sees the ORIGINAL payload and authorizes normally.
        self.assertTrue(self.verifier.verify(self.valid_action))

    # ------------------------------------------------------------------
    # Consumer-side boundary — provider-held registry (object identity)
    # ------------------------------------------------------------------

    def test_fail_manually_constructed_assertion(self):
        """VerifiedAssertion constructed outside the trusted ingress must fail closed."""
        forged = VerifiedAssertion(_auth=self.base_auth, _provider=self.provider)
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(forged)
        self.assertNotIn("req-123", self.verifier.auth_store)

    def test_fail_copied_assertion_fields(self):
        """Field-by-field copy of a legitimate assertion must fail closed."""
        # Sanity: the legitimate path works first.
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertTrue(self.verifier.verify(self.valid_action))

        # Forge a clone by copying the two fields of a legitimate assertion.
        forged = VerifiedAssertion(
            _auth=self.valid_assertion._auth,
            _provider=self.valid_assertion._provider,
        )
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(forged)

    def test_fail_assertion_from_unrelated_provider(self):
        """An assertion issued by a different provider must fail closed on our verifier."""
        other_provider = TrustedAuthorizationProvider()
        other_auth = make_auth(request_id="req-other", is_one_time=False)
        other_assertion = other_provider._mint(other_auth)
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
        auth = make_auth(request_id="req-999", allowed_paths=("*",))
        assertion = self.provider._mint(auth)
        self.verifier.grant_authorization(assertion)

        action = ActionRequest(
            request_id="req-999",
            task_id="task-456",
            repository="owner/repo",
            branch="feature/AGE-5",
            base_sha="abcdef1",
            target_sha="abcdef2",
            target_paths=["src/main.py"],
            operation="write_file",
            action_type="commit",
        )
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
        auth = make_auth(revoked=True)
        assertion = self.provider._mint(auth)
        self.verifier.grant_authorization(assertion)
        self.assertFalse(self.verifier.verify(self.valid_action))

    def test_fail_expired(self):
        auth = make_auth(expiry=time.time() - 100)
        assertion = self.provider._mint(auth)
        self.verifier.grant_authorization(assertion)
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