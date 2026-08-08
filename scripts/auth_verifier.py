import time
import typing
import os
import threading
from dataclasses import dataclass, field

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

@dataclass
class VerifiedAssertion:
    """
    Represents an authorization that has been cryptographically or systemically 
    verified as originating from the PO. This cannot be instantiated by regular 
    untrusted caller code (in a real system, the constructor would be private/sealed).
    """
    _auth: AuthContext
    _issuer_token: str

    @property
    def auth(self) -> AuthContext:
        return self._auth


class TrustedAuthorizationProvider:
    """
    The strict boundary that verifies PO signatures and issues VerifiedAssertions.
    In the reference model, it acts as the sole issuer of valid assertions.
    """
    def __init__(self, expected_system_token: str = "sys_internal_secret"):
        self._system_token = expected_system_token

    def issue_assertion(self, auth: AuthContext, po_cryptographic_signature: str) -> VerifiedAssertion:
        # In a real implementation, this verifies the cryptographic signature against the PO's public key.
        # Here we mock the boundary: only valid signatures produce an assertion.
        if not po_cryptographic_signature.startswith("VALID_PO_SIG_"):
            raise ValueError("Invalid cryptographic signature. Cannot issue trusted assertion.")
        return VerifiedAssertion(_auth=auth, _issuer_token=self._system_token)

    def is_valid_assertion(self, assertion: VerifiedAssertion) -> bool:
        return assertion._issuer_token == self._system_token


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
        # 1. Trusted provenance: verify the assertion itself was issued by our trusted provider
        if not self.trusted_provider.is_valid_assertion(assertion):
            raise ValueError("Untrusted assertion provenance. Cannot grant authorization.")

        auth = assertion.auth
        # Fail closed on duplicate/conflict instead of overwrite
        with self._lock:
            if auth.request_id in self.auth_store:
                raise ValueError(f"Authorization for request {auth.request_id} already exists. Conflicts fail closed.")
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
                return False # Fails closed if empty
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
            # No wildcard `*` support: strict exact/prefix bounding required
            if normalized_path == norm_a:
                return True
            prefix = norm_a if norm_a.endswith(os.sep) else norm_a + os.sep
            if normalized_path.startswith(prefix):
                return True
        return False
