import unittest
import time
import threading
from auth_verifier import (
    ActionRequest,
    AuthContext,
    AuthVerifier,
    POMintCapability,
    TrustedAuthorizationProvider,
    VerifiedAssertion,
    _POSignedEnvelope,
    po_sign_envelope,
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

        # Legitimate issuance path:
        #   po_sign_envelope → trusted_po_ingress (inside provider) → issue_assertion
        # None of these three steps is reachable via the AuthVerifier.
        self.valid_envelope = po_sign_envelope(self.base_auth)
        self.valid_assertion = self.provider.issue_assertion(
            self.base_auth, self.valid_envelope
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
            action_type="commit",
        )

    # ------------------------------------------------------------------
    # A. Issuer-side trust boundary
    # ------------------------------------------------------------------

    def test_legitimate_trusted_issuance_succeeds(self):
        """Full trusted pipeline: po_sign_envelope → ingress → issue_assertion → grant → verify."""
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertTrue(self.verifier.verify(self.valid_action))

    def test_fail_auth_verifier_does_not_expose_mint(self):
        """AuthVerifier must not expose any method that mints a VerifiedAssertion.

        The verifier is a verifier only. Even its public attribute
        ``trusted_provider`` must not be a usable minting authority on
        its own — issuing requires a PO-signed envelope the verifier
        does not produce.
        """
        forbidden_tokens = ("issue_", "mint_", "create_assertion", "new_assertion", "sign_")
        leaked = sorted(
            name
            for name in vars(self.verifier).keys()
            if any(token in name.lower() for token in forbidden_tokens)
        )
        self.assertEqual(
            leaked,
            [],
            f"AuthVerifier exposes mint-like attributes: {leaked}",
        )

        # No public method either.
        method_leaked = sorted(
            name
            for name in dir(self.verifier)
            if callable(getattr(self.verifier, name, None))
            and not name.startswith("_")
            and any(token in name.lower() for token in forbidden_tokens)
        )
        self.assertEqual(
            method_leaked,
            [],
            f"AuthVerifier exposes mint-like public methods: {method_leaked}",
        )

    def test_fail_provider_reference_does_not_grant_mint(self):
        """Holding the provider reference (even via the verifier) is not sufficient to mint.

        Even with the provider, ``issue_assertion`` requires a PO-signed
        envelope produced by ``po_sign_envelope``. An unsigned envelope
        is rejected by the trusted ingress.
        """
        # Caller obtains provider reference from the verifier
        provider_via_verifier = self.verifier.trusted_provider
        # An envelope constructed directly (not via po_sign_envelope) lacks
        # the PO signature marker.
        unsigned_envelope = _POSignedEnvelope(self.base_auth)
        with self.assertRaises(ValueError):
            provider_via_verifier.issue_assertion(self.base_auth, unsigned_envelope)

    def test_fail_non_envelope_rejected_at_ingress(self):
        """Non-envelope inputs (raw auth context, strings, None) are rejected by the ingress."""
        with self.assertRaises(ValueError):
            self.provider.issue_assertion(self.base_auth, self.base_auth)
        with self.assertRaises(ValueError):
            self.provider.issue_assertion(self.base_auth, "not an envelope")
        with self.assertRaises(ValueError):
            self.provider.issue_assertion(self.base_auth, None)
        # A raw POMintCapability is also not an envelope — the ingress
        # only accepts PO-signed envelopes, not pre-minted capabilities.
        with self.assertRaises(ValueError):
            self.provider.issue_assertion(self.base_auth, POMintCapability())

    def test_fail_unsigned_envelope_rejected_at_ingress(self):
        """An envelope constructed directly (not via po_sign_envelope) fails the ingress."""
        forged_envelope = _POSignedEnvelope(self.base_auth)
        # forged_envelope._signed_by_po is False by default
        with self.assertRaises(ValueError):
            self.provider.issue_assertion(self.base_auth, forged_envelope)

    def test_fail_arbitrary_auth_context_unauthorized(self):
        """An arbitrary AuthContext with no trusted issuance cannot be authorized."""
        # No grant has happened for this arbitrary request_id.
        arbitrary_action = ActionRequest(
            request_id="req-arbitrary",
            task_id="task-456",
            repository="owner/repo",
            branch="feature/AGE-5",
            base_sha="abcdef1",
            target_sha="abcdef2",
            target_paths=["docs/x.md"],
            operation="write_file",
            action_type="commit",
        )
        self.assertFalse(self.verifier.verify(arbitrary_action))

        # And even if we tried to bypass by constructing a VerifiedAssertion
        # manually with a real provider reference and a real POMintCapability,
        # it is still not in the provider's issuance registry and therefore
        # not authorized.
        forged = VerifiedAssertion(
            _auth=self.base_auth,
            _provider=self.provider,
            _mint_capability=POMintCapability(),
        )
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(forged)

    # ------------------------------------------------------------------
    # Object-identity / provider-held registry (consumer-side boundary)
    # ------------------------------------------------------------------

    def test_fail_manually_constructed_assertion(self):
        """VerifiedAssertion constructed outside issue_assertion must fail closed."""
        forged = VerifiedAssertion(
            _auth=self.base_auth,
            _provider=self.provider,
            _mint_capability=POMintCapability(),
        )
        with self.assertRaises(ValueError):
            self.verifier.grant_authorization(forged)
        self.assertNotIn("req-123", self.verifier.auth_store)

    def test_fail_copied_assertion_fields(self):
        """Field-by-field copy of a legitimate assertion must fail closed.

        Even when the forged object references the exact same provider
        instance and carries a copy of every field of a legitimate
        assertion, it is not in the provider's issuance registry and
        therefore has no provenance.
        """
        # Sanity: the legitimate path works first.
        self.verifier.grant_authorization(self.valid_assertion)
        self.assertTrue(self.verifier.verify(self.valid_action))

        # Forge a clone by copying the three fields of a legitimate assertion.
        forged = VerifiedAssertion(
            _auth=self.valid_assertion._auth,
            _provider=self.valid_assertion._provider,
            _mint_capability=self.valid_assertion._mint_capability,
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
        other_envelope = po_sign_envelope(other_auth)
        other_assertion = other_provider.issue_assertion(other_auth, other_envelope)
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
        envelope = po_sign_envelope(auth)
        assertion = self.provider.issue_assertion(auth, envelope)
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