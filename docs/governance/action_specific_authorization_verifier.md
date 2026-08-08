# Action-Specific Authorization Verifier

## Purpose
Define a strict authorization verifier that ensures any bounded workflow step or action is authorized by the Product Owner (PO) before it can proceed. The verifier acts as a gatekeeper, emitting a verified projection for the runtime state kernel, and never inferring authorization from context.

## Verification Dimensions
The following dimensions MUST be precisely validated:
1. **Trusted Authorization Provenance**: Authorization must originate exclusively from the PO. The trust boundary has two sides.
    - **Issuer-side boundary**: `TrustedAuthorizationProvider.issue_assertion` requires a `POMintCapability` produced by the module-level `trusted_po_ingress` function, which in turn requires a PO-signed envelope produced by the module-level `po_sign_envelope` function. None of these three functions is a method on `TrustedAuthorizationProvider` or `AuthVerifier`, and the verifier exposes no path to minting. An ordinary caller who possesses or discovers a reference to the provider (for example, via `verifier.trusted_provider`) still cannot mint, because `issue_assertion` rejects any envelope that is not a `_POSignedEnvelope` carrying the PO signature marker set by `po_sign_envelope`.
    - **Consumer-side boundary**: each issued assertion is registered in the provider's private `WeakSet`. `AuthVerifier.grant_authorization`, `verify`, and `consume` call `is_valid_assertion`, which requires both provider identity and registry membership. There is no caller-visible token string to guess or copy: provenance is determined entirely by provider-held object identity.
    
    Manually constructed `VerifiedAssertion` objects — even with copied fields, a real provider reference, and a real `POMintCapability` — fail the consumer-side provenance check. Direct construction of `_POSignedEnvelope` or `POMintCapability` at the Python language level is permitted but yields inputs the trusted ingress rejects, so it grants no mint authority. (Actual production cryptography remains explicitly out of scope for the AGE-5 isolated model.)
2. **Request and Task Binding**: The exact request ID and an independent mission/task ID must match.
3. **Repository and Branch Binding**: Exact repository name and branch name must match.
4. **Commit SHA Binding**: Exact base or target commit SHA must match.
5. **Allowed Paths / Scope**: The action must be strictly within the permitted paths/scope. Must be robust against path traversal (e.g. `../` or `/absolute/path`). Wildcard `*` paths are strictly disallowed in order to establish exact and bounded authorization semantics.
6. **Allowed Operation**: The specific file/system operation (e.g., `write_file`, `create_pr`) must match.
7. **Allowed Action Type**: The higher-level action context (e.g., `commit`, `push`, `merge`, `deploy`) must match.
8. **Expiry**: The authorization must not be expired.
9. **Revocation**: The authorization must not be revoked.
10. **One-time vs Reusable**: If marked as one-time, it cannot be consumed more than once. Consumption is separated from verification. Note: the AGE-5 reference implementation is a non-concurrent test model using a threading lock; true atomic transaction safety is a future runtime requirement.

## Security Constraints (Fail Closed)
The verifier MUST **fail closed** (reject) under the following conditions:
* Any required field is missing.
* Untrusted provenance (assertion was not issued by the `TrustedAuthorizationProvider`).
* Repository, branch, or commit SHA does not match.
* The requested scope exceeds the authorized scope (including traversal bypass and wildcards).
* The operation or action type does not match.
* The authorization has expired.
* The authorization has been revoked.
* A one-time authorization has already been consumed.
* The authorization is ambiguous or conflicting. Duplicate or conflicting grants for the same request ID MUST immediately throw an exception (fail closed), not overwrite.

### Inference Rules
* **No Contextual Inference**: Must NOT infer authorization from a PASS result, Linear status, CI success, or Agent suggestion.
* **No Escalation**: Must NOT infer `Ready`, `Merge`, or `Deploy` permissions from a basic `Implementation` (write/commit) permission.

## Boundary
This module is strictly for design and isolated test specification. No integration with real write-capable runtimes (e.g., GitHub, Linear, Outer Runner) is permitted in this phase (AGE-5 scope).
