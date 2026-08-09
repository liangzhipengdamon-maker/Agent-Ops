# AGE-31 — Status Report Delivery & Context Synchronization Design

> Design for the synchronization layer between Local Agent execution
> state, GitHub/Linear artifacts, GPT Web reviewer context, and PO
> decision context. AGE-24/27/28/29/30 extension. Planning-only. No
> production implementation.

## 1. Problem Statement

```
Local Agent State
        ≠
GPT Reviewer Context
        ≠
PO Channel Context
```

The Builder may correctly stop at a governance boundary, while the
controlling GPT/PO channel does not yet have the latest status report
unless manually forwarded. Reports can be generated and artifacts
delivered, but the participants do not share the same state at the same
time.

This is the synchronization gap identified in AGE-22 (PO handoff
delivery) and AGE-24 Phase 0.5 (transition controller), now addressed
as a first-class design.

## 2. Status Report Event Model

A status report is modeled as an **event** with the following fields:

| Field | Required | Meaning |
|---|---|---|
| `event_id` | yes | unique event id |
| `type` | yes | `STATUS_REPORT` / `REVIEW_REQUEST` / `REVIEW_RESULT` / `PO_HANDOFF` |
| `correlation_id` | yes | request/review correlation id (matches ACK) |
| `task_id` | yes | Linear task identifier |
| `repo` | yes | canonical repository |
| `pr` | yes | PR number |
| `head` | yes | exact reviewed HEAD SHA |
| `state` | yes | governance state (e.g. `WAITING_PO_AUTH`) |
| `summary` | yes | structured factual summary |
| `generated_at` | yes | timestamp |
| `delivery_targets` | yes | list: `gpt_web`, `po_channel`, `neutral_relay` |
| `ack_required` | yes | `true` |
| `authored_by` | yes | role: `builder` |

### 2.1 Completion event

A completion event is `type=STATUS_REPORT` with `state` indicating the
phase/stop state. It is **not** the same as a delivery.

### 2.2 Report artifact

The artifact is the structured event (JSON + Markdown body). It is the
**only** payload the delivery layer transports.

### 2.3 Delivery target

The event's `delivery_targets` enumerates which contexts must receive
it. At minimum: `gpt_web` (reviewer) and `po_channel`.

### 2.4 Acknowledgement

Each delivery target acknowledges with an event that carries the same
`correlation_id`. Acknowledged = the target has read it. Acknowledged ≠
authorized.

### 2.5 Correlation ID + HEAD binding

Every status event carries:
- `correlation_id` (a unique nonce, matches ACK),
- `repo` + `pr` + `head` (exact reviewed HEAD).

A stale event (wrong HEAD) or a mismatched ACK (wrong correlation_id) is
rejected.

## 3. Canonical Status Source

The single canonical source of the latest status is defined by a
**hierarchy**, not by any single store:

| Layer | Role | Authority |
|---|---|---|
| **Linear task state** | task objective + lifecycle | planning authority |
| **GitHub PR state** | review decision + PR/HEAD | **review evidence source of truth** |
| **Neutral Relay delivery** | transport of status events | transport only |
| **Local Agent `.agent-state`** | Builder local projection | Builder truth |
| **Canonical Status Record** | merged, bound projection (task+PR+HEAD) | **synchronization source of truth** |

### 3.1 Canonical Status Record

The **Canonical Status Record** is a single bound projection:

```
{
  "task_id": "...",
  "repo": "...",
  "pr": 1,
  "head": "<exact SHA>",
  "state": "<governance state>",
  "last_event_id": "...",
  "last_ack": {"gpt_web": <event_id>, "po_channel": <event_id>},
  "updated_at": "<ts>"
}
```

It is the value all contexts converge on. It is **derived** from Linear +
GitHub + Local Agent state; it is not a separate authority.

## 4. Delivery Contract

The delivery contract guarantees three distinct states (per AGE-22):

| State | Meaning | Guarantee |
|---|---|---|
| `REPORT_GENERATED` | event created | always true after generation |
| `REPORT_DELIVERED` | event reached all targets | must be verified by read-back |
| `REPORT_ACKNOWLEDGED` | each target read it | requires matching ACK |

### 4.1 Delivery guarantees

1. **Generation**: the Builder always produces a structured event.
2. **Delivery**: the delivery layer transmits the event to every
   `delivery_target`. Delivery is confirmed by reading the target's
   conversation/context back (the AGE-19 empirical read-back), not by
   assuming the transport succeeded.
3. **Acknowledgement**: each target responds with an ACK carrying the
   same `correlation_id` + `repo/pr/head`. The ACK is recorded in the
   Canonical Status Record.
4. **Failure recovery**: if a target does not ACK within a bounded wait,
   the delivery layer classifies the failure (delivered-not-acked /
   not-delivered / identity-drift) and retries within bounds or enters
   `WAIT_REVIEW` (fail closed).

### 4.2 Delivery failure recovery

| Failure | Classification | Recovery |
|---|---|---|
| GPT Web does not ACK | delivered-not-acked | bounded retry on next heartbeat |
| Relay transport fails | not-delivered | re-emit after verifying identity |
| HEAD drift | identity-drift | stop, do not re-deliver stale event |
| Unreadable target | ambiguous | `WAIT_REVIEW`, never fabricate |

## 5. Context Synchronization

The three contexts (Local Agent, GPT Web reviewer, PO channel) are kept
aligned by **event + read-back**, not by manual copy/paste.

### 5.1 Local Agent (Builder)

- Reads the Canonical Status Record on wake.
- Publishes a status event at every phase boundary.
- Never claims reviewer status.

### 5.2 GPT Web reviewer

- Receives the status event via the Neutral Relay.
- Reviews and returns a verdict/ACK.
- Its context is updated by the event it read; the Builder never assumes
  GPT Web "knows" without a delivered+acked event.

### 5.3 PO channel

- Receives the same bound event (PO handoff).
- ACKs receipt; decides authorization.
- The PO decision is a separate authorization event, not inferred from
  the status event.

### 5.4 Synchronization rule

> A context is **in sync** when it has either:
> - delivered + acked the latest Canonical Status Record event, or
> - explicitly produced a newer event.

No context is ever assumed to be in sync based on narrative alone.

## 6. ACK / Correlation / HEAD Binding

- **ACK**: `type=STATUS_ACK`, carries `correlation_id`, `repo`, `pr`,
  `head`, `ack_state`.
- **Correlation**: an ACK must match `correlation_id` of the event it
  acknowledges. Stale/mismatched ACK rejected.
- **HEAD binding**: both the event and its ACK must carry the exact
  reviewed HEAD. A review/ACK on a different HEAD is ignored.
- This mirrors the AGE-19 strict correlation contract (REVIEW_REQUEST_ID /
  REPO / PR / HEAD must all match).

## 7. Failure Recovery

Failure classes and recovery (summary):

| Failure | Detection | Action |
|---|---|---|
| Event generation interrupted | no Canonical Status Record write | regenerate on wake from Linear+GitHub+local |
| Delivery to GPT Web fails | no delivery confirmation | bounded re-emit (identity re-verified) |
| GPT Web ACK missing | no matching ACK record | retry; if persists -> WAIT_REVIEW |
| PO ACK missing | no PO channel ACK | PO handoff stays `PO_HANDOFF_REQUIRED` |
| Canonical Status Record diverges | diff against Linear+GitHub | reconcile by re-deriving the projection |
| HEAD drift | record HEAD != PR HEAD | stop, surface drift |

## 8. Governance Boundary

- **Local Agent is Builder, not Reviewer**: it never judges its own work.
- **GPT Web remains Independent Reviewer**: it reviews; it does not
  execute.
- **GitHub PR Review is evidence, not authorization**: `APPROVED` /
  `PASS` never grants merge/deploy.
- **PO authorization cannot be bypassed**: HIGH risk / merge / deploy
  always require the PO gate.
- **No automatic merge, no automatic deploy, no GPT Web replacement, no
  Human Gate bypass, no daemon implementation.**

## 9. Non-Goals

- No automatic merge.
- No automatic deploy.
- No replacement of GPT Web.
- No bypass of Human Gate.
- No daemon implementation (delivery is a phase-boundary step, not a
  background service).

## 10. Validation Target (future)

The future validation flow:

```
Builder status event
   ↓
Canonical Status Record update (bound task+PR+HEAD)
   ↓
Deliver to GPT Web + PO channel (Neutral Relay, identity-bound)
   ↓
Read-back delivery
   ↓
Match ACK (correlation_id + repo + pr + head)
   ↓
All contexts in sync -> next phase
```

## 11. Boundary

- Design only.
- No production implementation.
- No merge, no deploy.
- Local Execution Agent role only; GPT Web remains Independent Reviewer.
