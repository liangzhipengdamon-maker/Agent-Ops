# AGE-3 Design Report: Authority Mapping & Trusted Authorization Provider (Revision 4)

## 1. Authority Hierarchy
- **Product Owner (PO):** The sole source of truth and authority. Grants and revokes all permissions.
- **Trusted Auth Provider (TAP):** The secure isolation layer translating raw PO intent into strict, verifiable machine contracts.
- **Outer Runner:** The execution governor enforcing Step Authorization; guarantees "one-action-per-wake".
- **LoopX (State Kernel):** Purely passive persistence of status and agenda.
- **Agent Runtime:** The stateless proposer of actions. Cannot authorize itself.
- **Linear/CI/Reviews/LoopX:** Exclusively **evidence** or state signals. None can generate permissions.

---

## 2. The Four Core Contracts

To guarantee fail-closed execution without drift, authorization is split into distinct, enforceable contracts.

### A. Mission Authorization Envelope (Immutable Pre-Authorization)
Defines the long-term boundary of a mission. Once signed by the TAP, it is strictly **immutable**.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Mission Authorization Envelope",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "schema_version": { "type": "string", "const": "v1.0" },
    "mission_id": { "type": "string" },
    "issuer_identity": { "type": "string" },
    "authorization_mode": { "enum": ["dry_run", "local_only", "remote_mutation"] },
    "po_evidence_ref": { "type": "string" },
    "idempotency_key": { "type": "string" },
    "parent_authorization_id": { "type": ["string", "null"] },
    "issued_at": { "type": "string", "format": "date-time" },
    "expires_at": { "type": "string", "format": "date-time" },
    "permitted_terminal_stage": { "enum": ["LOCAL_READY", "DRAFT_PR", "READY_FOR_REVIEW", "MERGED", "DEPLOYED"] },
    "allowed_actions": {
      "type": "array",
      "uniqueItems": true,
      "items": { "enum": [
        "READ", "WRITE_FILE", "COMMIT", "CREATE_BRANCH", "DELETE_BRANCH", "PUSH",
        "CREATE_DRAFT_PR", "UPDATE_PR", "MARK_READY", "REQUEST_REVIEW", "SUBMIT_REVIEW",
        "LINEAR_WRITE", "ADD_EVIDENCE", "REBASE", "CHANGE_BASE", "MODIFY_WORKFLOW",
        "SECRET_WRITE", "DATABASE_MIGRATION", "EXTERNAL_API_WRITE", "MERGE", "DEPLOY"
      ]}
    },
    "prohibited_actions": { "type": "array", "uniqueItems": true, "items": { "type": "string" } },
    "risk_limit_binding": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "canonical_repository": { "type": "string" },
        "base_branch": { "type": "string" },
        "expected_base_sha": { "type": "string", "pattern": "^[0-9a-f]{40}$" },
        "base_sha_conflict_policy": { "enum": ["PINNED_BASE", "REBASE_AND_REVALIDATE", "PATH_CONFLICT_AWARE"] },
        "allowed_branches": { "type": "array", "uniqueItems": true, "items": { "type": "string" } },
        "allowed_paths": { "type": "array", "uniqueItems": true, "items": { "type": "string" } },
        "deny_paths": { "type": "array", "uniqueItems": true, "items": { "type": "string" } },
        "max_changed_files": { "type": "integer", "minimum": 0 },
        "max_added_lines": { "type": "integer", "minimum": 0 },
        "max_deleted_lines": { "type": "integer", "minimum": 0 },
        "max_commits": { "type": "integer", "minimum": 0 },
        "max_prs": { "type": "integer", "minimum": 0 },
        "max_wall_clock_seconds": { "type": "integer", "minimum": 0 },
        "max_model_tokens": { "type": "integer", "minimum": 0 },
        "max_cost_usd": { "type": "number", "minimum": 0 },
        "max_actions": { "type": "integer", "minimum": 0 },
        "allowed_dependencies": { "type": "array", "uniqueItems": true, "items": { "type": "string" } },
        "deny_generated_files": { "type": "boolean" },
        "database_migration_allowed": { "type": "boolean" },
        "workflow_change_allowed": { "type": "boolean" },
        "secret_access_allowed": { "type": "boolean" },
        "external_write_allowed": { "type": "boolean" },
        "production_allowed": { "type": "boolean" },
        "required_tests": { "type": "array", "uniqueItems": true, "items": { "type": "string" } },
        "required_review_verdict": { "enum": ["NONE", "APPROVAL_REQUIRED"] }
      },
      "required": [
        "canonical_repository", "base_branch", "expected_base_sha", "base_sha_conflict_policy",
        "allowed_branches", "allowed_paths", "deny_paths",
        "max_changed_files", "max_added_lines", "max_deleted_lines", "max_commits", "max_prs",
        "max_wall_clock_seconds", "max_model_tokens", "max_cost_usd", "max_actions",
        "allowed_dependencies", "deny_generated_files", "database_migration_allowed",
        "workflow_change_allowed", "secret_access_allowed", "external_write_allowed",
        "production_allowed", "required_tests", "required_review_verdict"
      ]
    },
    "required_gates": { "type": "array", "uniqueItems": true, "items": { "type": "string" } },
    "revocation_registry_ref": { "type": "string" },
    "fail_closed_policy_version": { "type": "string" },
    "evidence_requirements": { "type": "array", "uniqueItems": true, "items": { "type": "string" } }
  },
  "required": [
    "schema_version", "mission_id", "issuer_identity", "authorization_mode",
    "po_evidence_ref", "idempotency_key", "parent_authorization_id", "issued_at", "expires_at",
    "permitted_terminal_stage", "allowed_actions", "prohibited_actions", "risk_limit_binding",
    "required_gates", "revocation_registry_ref", "fail_closed_policy_version", "evidence_requirements"
  ]
}
```

**Semantic Validation Rules (Enforced Outside JSON Schema):**
- `expires_at` must be strictly greater than `issued_at`.
- `deny_paths` and `prohibited_actions` overrides `allowed_paths` and `allowed_actions`.
- `permitted_terminal_stage` must be consistent with `allowed_actions` (e.g. `DEPLOYED` stage requires `DEPLOY` action).
- If `production_allowed = false`, `DEPLOY` must not be present.
- If `workflow_change_allowed = false`, `MODIFY_WORKFLOW` must not be present.
- Every risk-limit field is mandatory. No implementation may silently substitute permissive defaults. A value of `0` is an explicit deny/zero-budget decision, not “unlimited”.

### B. Derived Action Authorization (Immutable)
Because the Mission Envelope validates future tasks, it cannot pre-approve arbitrary SHAs for high-risk terminal actions (`MARK_READY`, `MERGE`, `DEPLOY`). When the Agent generates a concrete commit, an immutable **Derived Action Authorization** is signed for that *exact* SHA.

**Immutable Structure:**
- `derived_authorization_id`
- `parent_mission_id`
- `action` (e.g., `MERGE`)
- `exact_head_sha`
- `base_sha_at_validation`
- `issued_at`
- `expires_at`
- `gate_evidence_hash`
- `nonce`
- `signature`

### C. Revocation, Execution & Consumption Record (Mutable State)
Both the Mission Envelope and the Derived Authorization are strictly immutable. Execution status, expiry, revocation, quota consumption, and kill-switches are stored in a **Mutable Trusted Revocation and Execution Registry** (referenced by `revocation_registry_ref` or equivalent).

For Derived Actions specifically, a **Mutable Derived Authorization Execution Record** maintains state:
- `derived_authorization_id`
- `status`: `ACTIVE` | `EXECUTING` | `CONSUMED` | `FAILED` | `REVOKED` | `EXPIRED`
- `execution_id`
- `claimed_at`
- `lease_expires_at`
- `attempt_count`
- `remote_idempotency_key`
- `result_evidence`
- `consumed_at`
- `execution_event_hash`

Execution follows a recoverable state machine:
1. The Outer Runner atomically performs `ACTIVE` → `EXECUTING`, assigning a unique `execution_id` and bounded execution lease.
2. The remote mutation is invoked with the strongest available idempotency and precondition controls, including exact PR/repository/action binding and exact expected HEAD/base SHAs.
3. The Runner reads back the remote system of record to determine whether the side effect occurred.
4. On verified success, it atomically performs `EXECUTING` → `CONSUMED` and stores result evidence.
5. On verified failure, it records `FAILED` with failure evidence.
6. If the Runner crashes while `EXECUTING`, recovery must reconcile against remote facts using `execution_id`, remote identifiers, exact SHAs, and result evidence before retrying or finalizing. Blind retry is forbidden.
7. Any state other than `ACTIVE` rejects a fresh execution claim. An expired execution lease permits recovery/reconciliation, not unconditional replay.

This contract does not claim a distributed exactly-once transaction across the registry and an external provider. It guarantees an **at-most-once authorization claim plus remote-side-effect reconciliation**. For GitHub merge, reconciliation uses repository/PR number, expected exact HEAD SHA, base state, and merged status. For deployment, the provider must expose an idempotency key, deployment ID, or equivalent verifiable operation identity; otherwise unattended deployment is prohibited.

### D. Step Authorization Decision (One-Action-Per-Wake)
On every wake, the Outer Runner evaluates the proposed action against Contracts A, B, and C. It returns exactly one bounded output and dictates wake control flow:
- **`ALLOW`**: Outer Runner executes exactly one action, records it, and immediately suspends the wake.
- **`DENY`**: Outer Runner records the refusal and immediately suspends execution until the next wake. (Or optionally allows max `max_proposals_per_wake: 1` before forcing a suspend). No infinite `while(true)` re-querying loop is permitted inside a single wake.
- **`STOP_AND_WAIT`**: Fatal drift, expired envelope, consumed limits, or active kill-switch. Runner records the blockage, terminates mission execution entirely, and yields control back to the PO.

---

## 3. Trusted Authorization Provider (TAP) Trust Contract
The TAP translates raw PO instructions into Envelopes. Its trust boundaries must be rigorously defined:
- **PO Input Channels:** Only cryptographically signed payloads, tightly bound specific Slack webhooks with identity validation, or direct authorized CLI invocations are accepted. (Ordinary Linear state changes are purely evidence, never a trigger).
- **Anti-Replay:** Every authorization request requires a unique `idempotency_key`/nonce.
- **Identity & Versioning:** Envelopes are cryptographically signed/hashed by the TAP, binding them to a specific `fail_closed_policy_version`.
- **Ambiguity & Conflict:** If multiple conflicting PO instructions exist, or if an instruction uses fuzzy logic (e.g., "deploy this if it looks good"), the TAP refuses to map it and outputs `WAIT`.
- **Revocation Supremacy:** A revocation instruction processed by the TAP instantaneously updates the Revocation Record, overriding any currently active Envelopes.

---

## 4. Base SHA Conflict Policies (`expected_base_sha`)
To handle long-running missions safely without causing unnecessary failure, the schema defines `base_sha_conflict_policy`:
1. **`PINNED_BASE`** (Default / Strictest / Default for v1): If `origin/main` changes by any commit, trigger `STOP_AND_WAIT`.
2. **`REBASE_AND_REVALIDATE`**: (Advanced Authorization Strategy) Allows `git rebase`. However, the runner suspends execution until the Agent re-runs tests, verifies the `risk_limit_binding` scope diff against the new base, and secures a Derived Action Authorization.
3. **`PATH_CONFLICT_AWARE`**: (**Future / Unsupported in v1**) Safely continues only if the new `main` commits strictly modify files entirely outside the active Envelope's `allowed_paths` and dependency graph. Disabled until robust dependency analyzers are qualified.

---

## 5. Audit Trail Contract
Every step must append an immutable record to the Audit Trail.
The trusted audit log is the canonical evidence record for Agent execution history, but it is **not an authorization source**.

- **Structure:** Uses a Hash-Chained Audit Event structure: `event_hash = SHA256(previous_event_hash + canonical_event_payload)`
- **Payload requires:** Envelope Hash, `mission_id`, Action Requested, Action Result, Before/After SHAs, Failure Evidence.
- **Contract Requirements:** 
  - `trusted writer identity`: Only the Outer Runner can append to the log.
  - `append acknowledgement`: Confirmed local or remote write.
  - `remote durable storage`: External immutable store syncing.
  - `periodic signed checkpoints` and a defined `genesis hash`.
  - `reconstruction procedure`: How to re-sync if local state is lost.

---

## 6. Threat Model
- **Privilege Escalation:** Agent attempts to self-broaden scope. *Mitigation:* Envelope is immutable; Outer Runner strictly drops out-of-scope steps.
- **Concurrency Drift:** Remote PR merged mid-mission. *Mitigation:* `PINNED_BASE` policy or `exact_head_sha` Derived Authorization immediately fails closed upon drift.
- **Unbounded Loops:** Agent spams actions or repeatedly proposes denied actions. *Mitigation:* Outer Runner enforced one-action-per-wake/one-proposal-per-wake (`ALLOW` or `DENY` both trigger a suspend).
- **Action Spoofing / Replay:** Agent replays an old deploy authorization. *Mitigation:* `exact_head_sha` Derived Authorization with `ACTIVE → EXECUTING → CONSUMED`, bounded lease, remote idempotency controls, and reconciliation prevents blind replay.

---

## 7. Open Owner Decisions (NEEDS_OWNER_DECISION)
- **Outer Runner Implementation:** What system (GitHub Actions, external orchestrator, local daemon) will run the Outer Runner loop to enforce the *One-Action-Per-Wake* constraint?
- **TAP Identity Mechanism:** What exact mechanism will be used to authenticate PO inputs (e.g., signed JWTs, dedicated Slack App credentials) and prevent spoofing?
- **Remote Audit Log Provider:** Where is the trusted remote durable storage location for the Hash-Chained Audit Trail?

---

## 8. Capability Matrix

| Capability | Verdict |
|---|---|
| Authority hierarchy | PASS |
| Evidence vs authority separation | PASS |
| Mission authorization concept | PASS |
| Step authorization concept | PASS |
| Default deny & Fail-closed principle | PASS |
| JSON Schema enforceability (Closed/Versioned/Semantic Validated) | PASS |
| Exact-SHA derived authorization (Ready/Merge/Deploy) | PASS |
| Derived Action Execution/Consumption Recovery | PASS |
| Mutable Revocation/Consumption architecture | PASS |
| Comprehensive Mandatory Risk-Limit bindings | PASS |
| TAP trust contract (Anti-replay/Identity) | PASS |
| Hash-chained Audit trail contract | PASS |
| One-action-per-wake (DENY suspend) | PASS |
| Outer Runner implementation choice | NEEDS_OWNER_DECISION |
