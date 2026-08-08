import os
import threading
import time
import typing
import weakref
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuthContext:
    """
    Immutable description of a proposed authorization.

    Frozen dataclass with tuple-typed collection fields so that the payload
    cannot be mutated after it is bound into a VerifiedAssertion. Fields are
    all assigned at construction time.
    """

    request_id: str
    task_id: str  # Independent mission/task binding
    repository: str
    branch: str
    base_sha: str
    target_sha: str
    allowed_paths: typing.Tuple[str, ...] = field(default_factory=tuple)
    allowed_operations: typing.Tuple[str, ...] = field(default_factory=tuple)
    allowed_action_types: typing.Tuple[str, ...] = field(default_factory=tuple)
    expiry: float = 0.0  # Unix timestamp
    revoked: bool = False
    is_one_time: bool = False


class VerifiedAssertion:
    """
    Opaque trusted authorization object, produced ONLY by
    ``TrustedAuthorizationProvider._mint`` (the private trusted ingress).

    The object is payload-bound and immutable: it embeds a frozen
    ``AuthContext`` at issuance time. After issuance:

      * the bound payload cannot be replaced (the object is frozen), and
      * the payload itself cannot be mutated (``AuthContext`` is frozen),
        so a modified or re-bound object can never still pass verification.

    There is deliberately no separate "proof" object: the trusted ingress
    produces the fully-bound trusted object in a single step, so a proof
    minted for Auth A cannot be replayed to authorize Auth B.
    """

    def __init__(
        self,
        _auth: "AuthContext",
        _provider: "TrustedAuthorizationProvider",
    ):
        # Issued objects are frozen after construction. The initial payload
        # binding bypasses __setattr__ on purpose; every later assignment is
        # rejected.
        object.__setattr__(self, "_auth", _auth)
        object.__setattr__(self, "_provider", _provider)

    @property
    def auth(self) -> "AuthContext":
        return self._auth

    def __setattr__(self, name, value):
        # Frozen after construction: no field may be reassigned post-issuance.
        raise AttributeError(
            f"VerifiedAssertion is immutable after issuance; cannot set {name!r}"
        )

    def __eq__(self, other):
        # Identity equality: two distinct objects are never equal, even if
        # they carry identical payload fields. This keeps the provider's
        # WeakSet registry membership strictly identity-based.
        return self is other

    def __hash__(self):
        return id(self)


class TrustedAuthorizationProvider:
    """
    Sole issuer of VerifiedAssertion objects.

    The trusted ingress is the private ``_mint`` method. It is the only
    path that creates and registers a VerifiedAssertion, and it binds the
    AuthContext into the trusted object in one step.

    ``_mint`` is deliberately private. The AuthVerifier is created via
    ``create_verifier()`` and does NOT hold a reference to this provider,
    so ordinary action/runtime code that only sees the verifier cannot
    reach the minting path. In production this private method would be a
    sealed capability (for example, backed by a cryptographic signature
    over the AuthContext); for the AGE-5 isolated reference model, the
    private trusted ingress is the expression of the boundary.
    """

    def __init__(self):
        self._issued: "weakref.WeakSet[VerifiedAssertion]" = weakref.WeakSet()

    def _mint(self, auth: "AuthContext") -> "VerifiedAssertion":
        # Trusted ingress: the only path that creates a VerifiedAssertion.
        # The payload is bound immutably at this point. There is no separate
        # proof object that could be attached to a different AuthContext.
        assertion = VerifiedAssertion(_auth=auth, _provider=self)
        self._issued.add(assertion)
        return assertion

    def is_valid_assertion(self, assertion: typing.Any) -> bool:
        # Consumer-side trust boundary: only objects this provider actually
        # minted are valid. A manually constructed or field-copied object —
        # even one referencing this provider — is not in the registry and
        # therefore fails closed. Non-assertion inputs also fail closed.
        return (
            isinstance(assertion, VerifiedAssertion)
            and assertion._provider is self
            and assertion in self._issued
        )

    def create_verifier(self) -> "AuthVerifier":
        # Returns a verifier that can only check provider-issued assertions.
        # The verifier does not retain a public reference to this provider,
        # so holding the verifier grants no path to minting.
        return AuthVerifier(checker=self.is_valid_assertion)


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
    Pure verifier of provider-issued assertions.

    Constructed from the provider's check function only. It does NOT hold a
    reference to ``TrustedAuthorizationProvider``, exposes no mint path, and
    cannot turn an arbitrary AuthContext into a trusted authorization.

    Only assertions that pass the provider's ``is_valid_assertion`` (that
    is, objects the provider actually minted) can be granted.
    ``grant_authorization`` is a registration step, not a mint step: it
    takes an already-issued trusted object and stores it under the
    request_id bound in its payload.
    """

    def __init__(self, checker: typing.Callable[[typing.Any], bool]):
        self.auth_store: typing.Dict[str, VerifiedAssertion] = {}
        self._checker = checker
        # Runtime consumption state for one-time authorizations. Kept OUT of
        # the trusted payload: consumption is verifier runtime state, not
        # part of the immutable authorization.
        self._consumed: typing.Set[str] = set()
        self._lock = threading.Lock()  # Model for transaction safety

    def grant_authorization(self, assertion: VerifiedAssertion):
        # Trusted provenance: confirm the assertion was actually issued by
        # the configured provider via its private registry. There is no
        # caller-visible token or separate proof to forge.
        if not self._checker(assertion):
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
            if not self._checker(assertion):
                return False

            auth = assertion.auth

            # Revocation & Expiry
            if auth.revoked:
                return False
            if time.time() > auth.expiry:
                return False

            # One-time consumption check
            if auth.is_one_time and action.request_id in self._consumed:
                return False

            # Identity & Binding matches
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

            # Scope, Operation & Action match
            if action.operation not in auth.allowed_operations:
                return False
            if action.action_type not in auth.allowed_action_types:
                return False

            # Path validation (strict exact or prefix match, no wildcards, no path traversal)
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
        Consumption state is kept in the verifier, never in the payload.
        """
        with self._lock:
            assertion = self.auth_store.get(request_id)
            if not assertion:
                return False

            # Re-check provenance on every consume: defend against store tampering.
            if not self._checker(assertion):
                return False

            if assertion.auth.is_one_time:
                if request_id in self._consumed:
                    return False
                self._consumed.add(request_id)
            return True

    def _is_path_allowed(self, path: str, allowed: typing.Iterable[str]) -> bool:
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