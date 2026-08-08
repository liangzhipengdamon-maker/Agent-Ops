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


class VerifiedAssertion:
    """
    An authorization that originates from a TrustedAuthorizationProvider.

    Provenance is NOT determined by inspectable string fields. The issuing
    provider maintains a private registry of the assertion objects it has
    minted; AuthVerifier only accepts assertions whose object identity is in
    that registry. A VerifiedAssertion constructed by any path other than
    ``TrustedAuthorizationProvider.issue_assertion`` — including any manual
    copy, even one that copies ``_auth`` and ``_provider`` from a
    legitimately-issued assertion — is not in the registry and therefore has
    no provenance.

    In production this boundary would be backed by cryptographic signatures
    over a private key held by the provider. For the AGE-5 isolated reference
    model, provider-held object identity is the minimal expression of the
    trust boundary.
    """

    def __init__(
        self,
        _auth: "AuthContext",
        _provider: "TrustedAuthorizationProvider",
    ):
        self._auth = _auth
        self._provider = _provider

    @property
    def auth(self) -> "AuthContext":
        return self._auth


class TrustedAuthorizationProvider:
    """
    Sole issuer of ``VerifiedAssertion`` objects.

    Each assertion minted by ``issue_assertion`` is registered in the
    provider's internal registry. The AuthVerifier calls
    ``is_valid_assertion`` to confirm an assertion is one this provider
    actually issued before granting authorization. Because the registry is the
    only source of truth, there is no caller-visible token string to guess,
    copy, or forge.
    """

    def __init__(self):
        self._issued: "weakref.WeakSet[VerifiedAssertion]" = weakref.WeakSet()

    def issue_assertion(self, auth: "AuthContext") -> "VerifiedAssertion":
        # Only path that registers an assertion into the provider's registry.
        assertion = VerifiedAssertion(_auth=auth, _provider=self)
        self._issued.add(assertion)
        return assertion

    def is_valid_assertion(self, assertion: "VerifiedAssertion") -> bool:
        # Trust boundary: only objects this provider actually minted are valid.
        # Manual construction — even with copied fields or a real provider
        # reference — fails closed.
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
    def __init__(self, trusted_provider: TrustedAuthorizationProvider):
        self.auth_store: typing.Dict[str, VerifiedAssertion] = {}
        self.trusted_provider = trusted_provider
        self._lock = threading.Lock()  # Model for transaction safety

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