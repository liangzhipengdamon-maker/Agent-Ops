# Action-Specific Authorization Verifier

## Purpose
Define a strict authorization verifier that ensures any bounded workflow step or action is authorized by the Product Owner (PO) before it can proceed. The verifier acts as a gatekeeper, emitting a verified projection for the runtime state kernel, and never inferring authorization from context.

## Verification Dimensions
The following dimensions MUST be precisely validated:
1. **Trusted Authorization Provenance**: Authorization must originate exclusively from the PO.
2. **Request and Task Binding**: The exact request ID or task identity must match.
3. **Repository and Branch Binding**: Exact repository name and branch name must match.
4. **Commit SHA Binding**: Exact base or target commit SHA must match.
5. **Allowed Paths / Scope**: The action must be strictly within the permitted paths/scope.
6. **Allowed Operation / Action Type**: Action type must match exactly (e.g., read, comment, commit, push, PR, Ready, merge, deploy, external-system write).
7. **Expiry**: The authorization must not be expired.
8. **Revocation**: The authorization must not be revoked.
9. **One-time vs Reusable**: If marked as one-time, it cannot be consumed more than once.

## Security Constraints (Fail Closed)
The verifier MUST **fail closed** (reject) under the following conditions:
* Any required field is missing.
* Repository, branch, or commit SHA does not match.
* The requested scope exceeds the authorized scope.
* The action type does not match.
* The authorization has expired.
* The authorization has been revoked.
* A one-time authorization has already been consumed.
* The authorization is ambiguous.

### Inference Rules
* **No Contextual Inference**: Must NOT infer authorization from a PASS result, Linear status, CI success, or Agent suggestion.
* **No Escalation**: Must NOT infer `Ready`, `Merge`, or `Deploy` permissions from a basic `Implementation` (write/commit) permission.

## Boundary
This module is strictly for design and isolated test specification. No integration with real write-capable runtimes (e.g., GitHub, Linear, Outer Runner) is permitted in this phase (AGE-5 scope).
