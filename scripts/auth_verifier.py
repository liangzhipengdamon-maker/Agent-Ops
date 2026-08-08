import os
import threading
import time
import typing
import weakref
from dataclasses import dataclass


@dataclass
class AuthContext:
    request_id: str
    task_id: str  # Independent mission/task binding
    repository: str
    branch: str
    base_sha: str
    target_sha: str
    allowed_paths: typing.List[str]
    allowed_operations: typing.List[str]  # e.g., ['write_file', 'create_pr']
    allowed_action_types: typing.List[str]  # e.g., ['commit', 'push', 'merge', 'deploy']
    expiry: float  # Unix timestamp
    revoked: bool = False
    is_one_time: bool = False
    consumed: bool = False


# ---------------------------------------------------------------------------
# Issuer-side trust boundary
# ---------------------------------------------------------------------------
# The boundary between the trusted PO authorization channel and the rest of
# the system. Only the module-level functions below may produce a usable
# POMintCapability. Ordinary caller code that holds a reference to the
# AuthVerifier or the TrustedAuthorizationProvider still cannot mint a
# VerifiedAssertion because it cannot satisfy the trusted_po_ingress check.
#
# In production this would be backed by a real cryptographic signature
# verified against the PO's registered public key. For the AGE-5 isolated
# reference model, the boundary is expressed structurally: the
# po_sign_envelope function stamps a marker that only trusted_po_ingress
# accepts, and the provider's issue_assertion requires a POMintCapability
# from the trusted ingress.


class _POSignedEnvelope:
    """
    Opaque envelope carrying an AuthContext for PO authorization issuance.

    Only envelopes produced by ``po_sign_envelope`` carry the marker the
    trusted ingress requires. Direct construction at the Python language
    level is permitted (the language does not seal classes) but yields an
    envelope the ingress rejects, so it grants no mint authority.
    """

    def __init__(self, auth: AuthContext):
        self._auth = auth
        # _signed_by_po is set ONLY by po_sign_envelope. Its absence causes
        # the trusted ingress to reject the envelope.
        self._signed_by_po = False


def po_sign_envelope(auth: AuthContext) -> _POSignedEnvelope:
    """
    The PO's trusted signing function. The only path that produces an
    envelope the trusted ingress will accept.

    In production this would emit a real cryptographic signature. In the
    AGE-5 isolated reference model, it stamps the envelope with the PO
    marker that the ingress checks for.

    This function is intentionally NOT a method on any class. It is the
    issuer-side trust boundary and must be invoked directly by the trusted
    PO authorization channel.
    """
    envelope = _POSignedEnvelope(auth)
    envelope._signed_by_po = True
    return envelope


class POMintCapability:
    """
    Opaque mint capability. Produced ONLY by ``trusted_po_ingress`` after
    a PO-signed envelope has been verified.

    Direct construction at the Python language level is permitted but
    useless: attaching a directly-constructed POMintCapability to a forged
    VerifiedAssertion still fails the provider's registry check, so it
    grants no mint authority.
    """

    def __init__(self):
        # No fields. The capability's value is its origin in the trusted
        # ingress call, not its content.
        pass


def trusted_po_ingress(po_signed_envelope: _POSignedEnvelope) -> POMintCapability:
    """
    The trusted ingress for PO authorization issuance. Verifies the input
    is a PO-signed envelope produced by ``po_sign_envelope`` and, if so,
    issues a POMintCapability.

    This function is the SOLE producer of POMintCapability objects. It is
    intentionally a module-level function — not a method on any class — so
    that an ordinary caller who possesses or has discovered a reference to
    the AuthVerifier or the TrustedAuthorizationProvider cannot reach a
    working mint path.
    """
    if not isinstance(po_signed_envelope, _POSignedEnvelope):
        raise ValueError(
            "Trusted ingress rejects the input: not a PO-signed envelope."
        )
    if not getattr(po_signed_envelope, "_signed_by_po", False):
        raise ValueError(
            "Trusted ingress rejects the envelope: PO signature marker "
            "missing. Only envelopes produced by po_sign_envelope are "
            "accepted."
        )
    return POMintCapability()


# ---------------------------------------------------------------------------
# Provider and Verifier
# ---------------------------------------------------------------------------


class VerifiedAssertion:
    """
    An authorization that originates from a TrustedAuthorizationProvider.

    Provenance is NOT determined by inspectable string fields. The issuing
    provider maintains a private registry of the assertion objects it has
    minted; AuthVerifier only accepts assertions whose object identity is in
    that registry. A VerifiedAssertion constructed by any path other than
    ``TrustedAuthorizationProvider.issue_assertion`` — including any manual
    copy, even one that copies ``_auth``, ``_provider``, and
    ``_mint_capability`` from a legitimately-issued assertion — is not in
    the registry and therefore has no provenance.
    """

    def __init__(
        self,
        _auth: "AuthContext",
        _provider: "TrustedAuthorizationProvider",
        _mint_capability: POMintCapability,
    ):
        self._auth = _auth
        self._provider = _provider
        self._mint_capability = _mint_capability

    @property
    def auth(self) -> "AuthContext":
        return self._auth


class TrustedAuthorizationProvider:
    """
    Sole issuer of VerifiedAssertion objects.

    ``issue_assertion`` requires a POMintCapability from the trusted
    ingress (``trusted_po_ingress``), which in turn requires a PO-signed
    envelope produced by ``po_sign_envelope``. Ordinary callers — including
    those that have discovered or hold a reference to this provider via the
    AuthVerifier — cannot mint assertions because they cannot satisfy the
    ingress check.

    In production the ingress would verify a real cryptographic signature
    against the PO's registered public key. For the AGE-5 isolated
    reference model, the structural separation between
    ``po_sign_envelope`` and ``trusted_po_ingress`` and the provider's
    requirement for a POMintCapability express the boundary.
    """

    def __init__(
        self,
        ingress: typing.Callable[[_POSignedEnvelope], POMintCapability] = trusted_po_ingress,
    ):
        self._issued: "weakref.WeakSet[VerifiedAssertion]" = weakref.WeakSet()
        self._ingress = ingress

    def issue_assertion(
        self,
        auth: AuthContext,
        po_signed_envelope: _POSignedEnvelope,
    ) -> VerifiedAssertion:
        # Issuer-side trust boundary: must obtain a mint capability from the
        # trusted ingress. Ordinary callers cannot satisfy this because they
        # cannot produce envelopes the ingress accepts.
        mint_capability = self._ingress(po_signed_envelope)
        assertion = VerifiedAssertion(
            _auth=auth,
            _provider=self,
            _mint_capability=mint_capability,
        )
        self._issued.add(assertion)
        return assertion

    def is_valid_assertion(self, assertion: VerifiedAssertion) -> bool:
        # Trust boundary on the consumer side: only objects this provider
        # actually minted are valid. Manual construction — even with
        # copied fields, a real provider reference, and a real mint
        # capability — fails closed because the forged object is not in
        # this registry.
        return (
            assertion is not None
            and assertion._provider is self
            and assertion in self._issued
        )


@dataclass
class ActionRequest:
    request_id: str
    task_id: str
    repository: str
    branch: str
    base_sha: str
    target_sha: str
    target_paths: typing.List[str]
    operation: str
    action_type: str


class AuthVerifier:
    """
    Pure verifier of provider-issued assertions. Does NOT expose any path
    to minting a VerifiedAssertion.

    The verifier holds a reference to the provider only so it can call
    ``is_valid_assertion`` to confirm provenance. The provider's
    ``issue_assertion`` still requires a POMintCapability from the trusted
    ingress — which is NOT obtainable through this verifier.

    No method on this class creates a VerifiedAssertion. ``grant_authorization``
    only registers an already-issued assertion that has passed
    ``is_valid_assertion``; it is a registration step, not a mint step.
    """

    def __init__(self, trusted_provider: TrustedAuthorizationProvider):
        self.auth_store: typing.Dict[str, VerifiedAssertion] = {}
        self.trusted_provider = trusted_provider
        self._lock = threading.Lock()  # Model for transaction safety

    # NOTE: AuthVerifier exposes NO method that creates a VerifiedAssertion.
    # To mint an assertion, a caller must use:
    #   po_sign_envelope(auth) → trusted_po_ingress(envelope) → provider.issue_assertion(auth, envelope)
    # None of those three functions is reachable through this verifier.

    def grant_authorization(self, assertion: VerifiedAssertion):
        # 1. Trusted provenance: confirm the assertion was actually issued by
        #    the configured provider via its private registry. There is no
        #    caller-visible token to forge.
        if not self.trusted_provider.is_valid_assertion(assertion):
            raise ValueError("Untrusted assertion provenance. Cannot grant authorization.")

        auth = assertion.auth
        # Fail closed on duplicate/conflict instead of overwrite
        with self._lock:
            if auth.request_id in self.auth_store:
                raise ValueError(
                    f"Authorization for request {auth.request_id} already exists. "
                    "Conflicts fail closed."
                )
            self.auth_store[auth.request_id] = assertion

    def verify(self, action: ActionRequest) -> bool:
        """
        Verify if the given action request is authorized.
        Fails closed on any mismatch.
        """
        with self._lock:
            assertion = self.auth_store.get(action.request_id)
            if not assertion:
                return False

            # Re-check provenance on every verify: enforce the trust boundary
            # uniformly and defend against store tampering.
            if not self.trusted_provider.is_valid_assertion(assertion):
                return False

            auth = assertion.auth

            # 2. Revocation & Expiry
            if auth.revoked:
                return False
            if time.time() > auth.expiry:
                return False

            # 3. One-time consumption check
            if auth.is_one_time and auth.consumed:
                return False

            # 4. Identity & Binding matches
            if auth.task_id != action.task_id:
                return False
            if auth.repository != action.repository:
                return False
            if auth.branch != action.branch:
                return False
            if auth.base_sha != action.base_sha:
                return False
            if auth.target_sha != action.target_sha:
                return False

            # 5. Scope, Operation & Action match
            if action.operation not in auth.allowed_operations:
                return False
            if action.action_type not in auth.allowed_action_types:
                return False

            # 6. Path validation (strict exact or prefix match, no wildcards, no path traversal)
            if not action.target_paths:
                return False  # Fails closed if empty
            for path in action.target_paths:
                if not self._is_path_allowed(path, auth.allowed_paths):
                    return False

            return True

    def consume(self, request_id: str) -> bool:
        """
        Explicitly consume a one-time authorization safely.
        Modeled with a threading.Lock to represent atomic transaction safety.
        """
        with self._lock:
            assertion = self.auth_store.get(request_id)
            if not assertion:
                return False

            # Re-check provenance on every consume: defend against store tampering.
            if not self.trusted_provider.is_valid_assertion(assertion):
                return False

            auth = assertion.auth
            if auth.is_one_time:
                if auth.consumed:
                    return False
                auth.consumed = True
            return True

    def _is_path_allowed(self, path: str, allowed: typing.List[str]) -> bool:
        # Prevent directory traversal bypass
        normalized_path = os.path.normpath(path)
        if ".." in normalized_path.split(os.sep) or normalized_path.startswith("/"):
            return False

        for a in allowed:
            norm_a = os.path.normpath(a)
            # No wildcard `*` support: strict exact/prefix bounding required.
            # Wildcard entries in the allow-list are treated literally as
            # exact directory/file names and therefore cannot authorize any
            # other path.
            if normalized_path == norm_a:
                return True
            prefix = norm_a if norm_a.endswith(os.sep) else norm_a + os.sep
            if normalized_path.startswith(prefix):
                return True
        return False