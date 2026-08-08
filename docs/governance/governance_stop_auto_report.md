# Governance Stop Auto-Report & ACK-Before-Stop Protocol

## Objective
To ensure that whenever an AgentOps task reaches a governance stop state, it reliably informs the external GPT Reviewer before halting execution. This prevents silent stops and ensures the Reviewer is always aware of the exact final state without requiring manual PO intervention.

## Allowed Stop States
The protocol recognizes the following states as valid governance stop states:
- `DONE`
- `WAITING_PO_AUTH`
- `BLOCKED`
- `NEEDS_OWNER_DECISION`
- `CHANGES_REQUESTED`

## Canonical Protocol Flow
1. `ENTER_STOP_STATE` (Internal state transitions to one of the allowed stop states).
2. `authoritative remote read-back` (Ensure the local state reflects the remote canonical repository).
3. `build exactly one status_report` (Construct the standardized report).
4. `send via Neutral Relay` (Dispatch the report to the Reviewer).
5. `wait for strictly correlated ACK` (Wait for an acknowledgment matching the exact request ID).
6. `record ACK` (Store `stop_episode.acked = true` for the exact `request_id`/`state`/`PR`/`HEAD`-bound stop episode, to prevent duplicates).
7. `STOP` (Halt execution).

## Report Contract
The generated `status_report` must follow this exact format:
```
REVIEW_REQUEST_ID: <new UUID>
REPO: <exact repo>
PR: <exact PR>
HEAD: <exact bound HEAD>
REQUEST: status_report
STATE: <stop state>
SUMMARY: <concise factual summary>
UNAUTHORIZED_ACTIONS: NONE|<explicit list>
```

> **AGE-18 v1 requires a PR-bound task.** Non-PR stop reporting (`PR: NONE`) is outside this protocol version.

## ACK Contract
The GPT Reviewer MUST respond with:
```
REVIEW_REQUEST_ID: <same UUID>
REPO: <exact repo>
PR: <exact PR>
HEAD: <exact bound HEAD>
ACK: status_report_received
```

## Invariants
- `status_report` and `ACK` are purely informational and constitute **evidence only**. They do not authorize any further actions (no Ready, Merge, Deploy, or subsequent tasks).
- The `ACK` must perfectly match the `REVIEW_REQUEST_ID`, `REPO`, `PR`, and `HEAD`. Stale or mismatched ACKs are rejected and the agent remains stopped.
- Idempotency: One stop episode results in at most one acknowledged report. Restarts after ACK do not resend the report unless the underlying state has been mutated by a new authorization. The `stop_episode.acked = true` flag binds ACK to the exact `request_id`/`state`/`PR`/`HEAD` stop episode.
- Unacknowledged or unknown-result cases must retry until resolved; they must not duplicate reports blindly.
- The Builder must autonomously complete this flow without manual PO relay.
