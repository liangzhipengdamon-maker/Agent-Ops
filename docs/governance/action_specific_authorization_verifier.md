# Action-Specific Authorization Verifier — Current Boundary

## Purpose

The authorization verifier protects **protected actions** and enforces exact authorization bindings. It is not a per-file/per-command brake on ordinary implementation inside an already authorized task/scope.

## Core rules

1. **PO provenance** — protected-action authorization originates only from explicit Product Owner authority captured by the trusted authorization path.
2. **No contextual inference** — PASS, Linear state, CI, timers, reports, transport success, or Agent suggestions never create permission.
3. **No escalation** — implementation permission does not imply Ready, Merge, Deploy, force push, production access, or authorization-policy changes.
4. **Fail closed** — missing, stale, ambiguous, conflicting, expired, revoked, or mismatched authorization is denied.
5. **Scope binding** — repository/task/scope/action must match the active authorization boundary.
6. **Exact commit binding where applicable** — a protected action that acts on an already-existing commit must bind the exact live 40-character HEAD required by that gate.

## Implementation authorization vs protected-action authorization

### Implementation authorization

Ordinary implementation is authorized against the active task/base/scope boundary. It may cover the normal sequence:

```text
edit → test → fix → commit → push → update draft PR → address review
```

It must **not** require the final future HEAD before implementation creates that HEAD.

### Protected-action authorization

Separate explicit PO authorization is required for protected actions including:

- Ready for Review
- Merge
- Deploy / production access
- force push / main-history rewrite
- authorization-policy or authorization-scope changes
- other actions classified HIGH by the canonical risk policy

Where such an action acts on an existing commit, exact current HEAD binding is mandatory.

## Verifier dimensions

For the protected action being checked, validate the fields relevant to the gate, including:

- trusted authorization provenance;
- request/task identity;
- repository and branch;
- exact current commit/base binding when required by the action;
- allowed scope;
- allowed operation/action type;
- expiry/revocation;
- one-time consumption where the gate is one-time;
- remote-state reconciliation before and after mutation.

No field may be silently widened or inferred from unrelated evidence.

## Relationship to risk policy

The authorization verifier and risk classifier are separate responsibilities:

- Risk policy decides `LOW / MEDIUM / HIGH` routing.
- Authorization verifier checks whether a concrete protected action is authorized.

A watcher/adapter must not replace the canonical risk policy with a local ad-hoc classifier, and the verifier must not turn review evidence into authorization.

## Historical AGE-5 note

Earlier AGE-5 text described an isolated test-phase boundary and prohibited integration during that specific phase. That was a **phase constraint**, not a permanent prohibition on later runtime integration. Current integration follows `AGE-20_GOVERNANCE_BASELINE_V1.md`.
