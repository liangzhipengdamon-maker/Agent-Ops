import time
import typing
import os
from dataclasses import dataclass

@dataclass
class AuthContext:
    trusted_signature: str  # Must not be just a simple string, should represent a cryptographic signature from PO
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
    def __init__(self):
        self.auth_store: typing.Dict[str, AuthContext] = {}

    def grant_authorization(self, auth: AuthContext):
        # Fail closed on duplicate/conflict instead of overwrite
        if auth.request_id in self.auth_store:
            raise ValueError(f"Authorization for request {auth.request_id} already exists. Conflicts fail closed.")
        self.auth_store[auth.request_id] = auth

    def verify(self, action: ActionRequest) -> bool:
        """
        Verify if the given action request is authorized.
        Fails closed on any mismatch.
        """
        auth = self.auth_store.get(action.request_id)
        if not auth:
            return False
            
        # 1. Trusted provenance (mock validation of signature)
        if not self._is_valid_po_signature(auth.trusted_signature):
            return False

        # 2. Revocation & Expiry
        if auth.revoked:
            return False
        if time.time() > auth.expiry:
            return False

        # 3. One-time consumption check (consumption is now separate, but we verify it's not already consumed)
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
            
        # 6. Path validation (prevent path traversal like '../')
        for path in action.target_paths:
            if not self._is_path_allowed(path, auth.allowed_paths):
                return False

        return True

    def consume(self, request_id: str) -> bool:
        """
        Explicitly consume a one-time authorization safely.
        """
        auth = self.auth_store.get(request_id)
        if not auth:
            return False
        if auth.is_one_time:
            if auth.consumed:
                return False
            auth.consumed = True
        return True

    def _is_valid_po_signature(self, signature: str) -> bool:
        # In a real implementation, this would verify a cryptographically secure signature or token.
        return signature.startswith("valid_po_sig_")

    def _is_path_allowed(self, path: str, allowed: typing.List[str]) -> bool:
        # Prevent directory traversal bypass
        normalized_path = os.path.normpath(path)
        if ".." in normalized_path.split(os.sep) or normalized_path.startswith("/"):
            return False

        for a in allowed:
            norm_a = os.path.normpath(a)
            if norm_a == "*":
                return True
            if normalized_path == norm_a:
                return True
            prefix = norm_a if norm_a.endswith(os.sep) else norm_a + os.sep
            if normalized_path.startswith(prefix):
                return True
        return False
