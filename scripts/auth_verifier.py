import time
import typing
from dataclasses import dataclass, field

@dataclass
class AuthContext:
    provenance: str  # Must be 'PO'
    request_id: str
    repository: str
    branch: str
    base_sha: str
    target_sha: str
    allowed_paths: typing.List[str]
    allowed_action_types: typing.List[str]  # read, commit, push, PR, Ready, merge, deploy
    expiry: float  # Unix timestamp
    revoked: bool = False
    is_one_time: bool = False
    consumed: bool = False

@dataclass
class ActionRequest:
    request_id: str
    repository: str
    branch: str
    base_sha: str
    target_sha: str
    target_paths: typing.List[str]
    action_type: str

class AuthVerifier:
    def __init__(self):
        # A mock store for authorizations (in memory for isolated test spec)
        self.auth_store: typing.Dict[str, AuthContext] = {}

    def grant_authorization(self, auth: AuthContext):
        self.auth_store[auth.request_id] = auth

    def verify(self, action: ActionRequest) -> bool:
        """
        Verify if the given action request is authorized.
        Fails closed on any mismatch.
        """
        auth = self.auth_store.get(action.request_id)
        if not auth:
            return False
            
        # 1. Trusted provenance
        if auth.provenance != "PO":
            return False

        # 2. Revocation & Expiry
        if auth.revoked:
            return False
        if time.time() > auth.expiry:
            return False

        # 3. One-time consumption check
        if auth.is_one_time and auth.consumed:
            return False

        # 4. Identity & Binding matches
        if auth.repository != action.repository:
            return False
        if auth.branch != action.branch:
            return False
        if auth.base_sha != action.base_sha:
            return False
        if auth.target_sha != action.target_sha:
            return False

        # 5. Scope & Action match
        if action.action_type not in auth.allowed_action_types:
            return False
            
        # All target paths must be strictly within allowed paths (simplified subset check)
        # If allowed_paths contains "*", we consider it a wild card for simplicity, 
        # but in a strict design we want exact prefix match.
        for path in action.target_paths:
            if not self._is_path_allowed(path, auth.allowed_paths):
                return False

        # If everything passes and it's one-time, consume it
        if auth.is_one_time:
            auth.consumed = True

        return True

    def _is_path_allowed(self, path: str, allowed: typing.List[str]) -> bool:
        for a in allowed:
            if a == "*":
                return True
            if path == a:
                return True
            # if a is 'docs/', it matches 'docs/governance.md'
            # if a is 'docs', it matches 'docs/governance.md'
            prefix = a if a.endswith("/") else a + "/"
            if path.startswith(prefix):
                return True
        return False
