# AGE-33 — Full Status Artifact Delivery & Context Hydration Design

> Design to close the remaining synchronization gap found in AGE-32:
> status events reach GPT Web via Neutral Relay, but the full PO status
> artifact is not automatically hydrated into the GPT context.
> Planning-only. No production implementation.

## 1. Problem Statement

AGE-32 validation result:

```
Status Event Delivery        PASS
Full Report Artifact Sync    PARTIAL
Strict ACK Capture           PARTIAL
```

Current flow (event summary only):

```
Local Agent
    ↓
Generate Full Status Report
    ↓
Neutral Relay
    ↓
GPT Web receives event summary
```

Required flow (event + full artifact + hydration + read-back + ACK):

```
Local Agent
    ↓
Status Event
    ↓
Full Report Artifact
    ↓
Neutral Relay
    ↓
GPT Web Context Hydration
    ↓
Read-back Verification
    ↓
ACK
```

The gap: GPT Web receives the notification event, but the **full report
package** (the complete artifact) is not delivered into the GPT context
without manual forwarding.

## 2. Report Artifact Model

### 2.1 Separation of event and artifact

The delivery is split into two bound objects:

- **Status Event** (notification): small, machine-readable pointer.
- **Full Report Artifact** (content): the complete report the reviewer
  needs.

### 2.2 Artifact identity

| Field | Required | Meaning |
|---|---|---|
| `artifact_id` | yes | unique artifact id (e.g. `art_<uuid>`) |
| `event_id` | yes | the event that references it |
| `correlation_id` | yes | shared with event + ACK |
| `repo` | yes | canonical repo |
| `pr` | yes | PR number |
| `head` | yes | exact reviewed HEAD SHA |
| `task_id` | yes | Linear task |
| `content` | yes | full report body |
| `content_type` | yes | `text/markdown` |
| `content_hash` | yes | SHA-256 of normalized content (integrity) |
| `generated_at` | yes | timestamp |
| `authored_by` | yes | `builder` |

### 2.3 Correlation binding

- `correlation_id` binds event ↔ artifact ↔ ACK.
- `repo + pr + head` binds the artifact to the exact reviewed state.
- `content_hash` binds the delivered content to what was generated (a
  re-hydration can verify the artifact was not tampered with).

## 3. Context Hydration Contract

### 3.1 What GPT Web must receive

GPT Web receives a **hydrated packet**:

```
HYDRATED_STATUS_PACKET
  event:      <Status Event (pointer fields)>
  artifact:   <Full Report Artifact (content, hash)>
  context:    <required context: PR URL, diff/commit refs, CI result>
  ack_target: <correlation_id + artifact_id to acknowledge>
```

Hydration means the GPT Web context contains the **full artifact
content**, not just a pointer to it.

### 3.2 Delivery method

- The Neutral Relay transports the **hydrated packet** (event +
  artifact + context) in a single bound message.
- This is transport-only (AGE-19). The relay does not judge content.
- The relay correlates the delivery to `correlation_id` and verifies
  `repo/pr/head` (AGE-19 strict correlation).

### 3.3 Acknowledgement target

- GPT Web ACKs with `correlation_id` + `artifact_id` (the artifact it
  actually received).
- A mismatch (wrong artifact_id) → the hydration is retried or fails
  closed.

## 4. Event vs Artifact Separation

| Layer | Role | Confirmation |
|---|---|---|
| Notification event | small pointer: task/pr/head/state | delivery confirmed by read-back |
| Full report artifact | complete content (hash-bound) | hydration confirmed by read-back (artifact_id + hash present) |
| Read-back | verify GPT context actually contains the artifact | post-delivery re-read of the GPT conversation |

The event alone is **not** sufficient. A task is "synchronized" only when
the full artifact is present in the target context AND verified by
read-back.

## 5. ACK Contract Extension

### 5.1 Strict ACK format

```
REVIEW_REQUEST_ID: <correlation_id>
REPO: <exact repo>
PR: <exact pr>
HEAD: <exact head>
ARTIFACT_ID: <artifact_id>
CONTENT_HASH: <sha256 of content>
ACK: artifact_hydrated
```

### 5.2 Rules

- `correlation_id`, `repo`, `pr`, `head`, `artifact_id` must all match.
- `CONTENT_HASH` must match the generated artifact's hash.
- **Bounded wait**: the Builder waits a bounded time for the ACK.
- **Retry**: if no ACK within the bound, classify (delivered-not-acked /
  not-delivered / identity-drift) and either retry or enter
  `WAIT_REVIEW` (fail closed).
- Never fabricate an ACK.

### 5.3 Failure handling

| Failure | Classification | Action |
|---|---|---|
| ACK missing | delivered-not-acked | bounded retry, then WAIT_REVIEW |
| artifact_id mismatch | wrong artifact | re-deliver the correct artifact |
| hash mismatch | tampered/partial | fail closed, surface |
| HEAD drift | identity drift | stop, do not re-hydrate stale |

## 6. Full Synchronization Chain

```
Local Agent
    ↓ build Status Event + Full Report Artifact
Status Event + Artifact (bound by correlation_id + repo/pr/head + hash)
    ↓
Neutral Relay (AGE-19, identity-bound, transport-only)
    ↓
GPT Web Context Hydration (event + full content + context)
    ↓
Read-back Verification (GPT conversation contains artifact_id + hash)
    ↓
Strict ACK (correlation_id + artifact_id + hash)
    ↓
All contexts in sync
```

## 7. Governance Boundary

- **Local Agent is Builder, not Reviewer**: it generates the artifact; it
  does not judge it.
- **GPT Web remains Independent Reviewer**: it reviews the hydrated
  artifact; it does not execute.
- **GitHub PR Review is evidence, not authorization**: `APPROVED` /
  `PASS` never grants merge/deploy.
- **PO authorization cannot be bypassed**: merge/deploy/PO gates remain.
- **No automatic merge, no automatic deploy, no GPT Web replacement, no
  authorization bypass, no scheduler implementation.**

## 8. Non-Goals

- No auto merge.
- No auto deploy.
- No GPT Web replacement.
- No authorization bypass.
- No scheduler implementation (hydration is a phase-boundary step, not a
  background service).

## 9. Validation Target (future)

The future validation flow (mirrors AGE-32 but with full artifact):

```
Local Agent -> WAITING_PO_AUTH
  ↓
Status Event + Full Report Artifact
  ↓
Neutral Relay -> GPT Web Context Hydration
  ↓
Read-back: artifact_id + hash present in GPT conversation
  ↓
Strict ACK (correlation_id + artifact_id + hash)
```

## 10. Boundary

- Design only.
- No production implementation.
- No merge, no deploy.
- Local Execution Agent role only; GPT Web remains Independent Reviewer.
