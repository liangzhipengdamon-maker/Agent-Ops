# AGE-21R Long Task Automation Gap Analysis

> Planning-only governance gap analysis.
> Derived from the AGE-21 Long Task Automation Pilot.
> This document analyzes manual intervention points and required future
> capabilities. It does **not** implement automation.

## 1. Completion Handoff Problem

An Agent can complete execution, create artifacts, create a PR, and send
an Independent Review Request — but the **completion state is not
guaranteed to be delivered and acknowledged** by the controlling Product
Owner.

### 1.1 Why artifact creation is not equivalent to communication

An artifact (a PR, a commit, a branch, a documentation file) **exists** in
a remote system. However:

- Existence of the artifact does not mean the controlling PO has been
  notified.
- Existence does not mean the PO has read the artifact.
- Existence does not mean the PO has acknowledged that the work reached a
  specific governance state.

Without a **formal handoff event**, the Agent and the PO live in two
separate timelines. The Agent believes "I finished". The PO may not yet
know that finishing happened.

### 1.2 Why STOP alone is insufficient

`STOP_AND_WAIT` (governed by AGE-18) halts execution on ambiguity or
drift. But a clean STOP does not constitute a **handoff**:

- STOP halts the Agent. It does not deliver a status report to the PO.
- STOP records a stop state in the audit trail. It does not request
  acknowledgement from the PO.
- STOP terminates the wake. If the Agent never wakes again, the PO has
  no formal signal that the work reached STOP.

Therefore STOP must be followed by an explicit **handoff** to be a true
governance transition.

## 2. Governance State Model

A future state flow (not implemented by AGE-22):

```
EXECUTION_COMPLETE
        |
        v
ARTIFACT_READY
        |
        v
REVIEW_REQUEST_SENT
        |
        v
PO_HANDOFF_REQUIRED
        |
        v
PO_HANDOFF_CONFIRMED
        |
        v
WAITING_PO_AUTH
```

Each state has a **single owner** and a **single transition rule**:

| State | Owner | Meaning | Transition |
|---|---|---|---|
| `EXECUTION_COMPLETE` | Builder / Runner | All planned actions for the task have been performed locally. | Builder emits an artifact (PR / branch / commit). |
| `ARTIFACT_READY` | Builder / Runner | The artifact exists on the remote and the exact identifier (PR number, branch, HEAD SHA) is known. | Builder dispatches a Review Request through the Neutral Relay. |
| `REVIEW_REQUEST_SENT` | Relay | The Review Request has been transmitted to the configured reviewer conversation. Identity-binding diagnostics confirm. | Reviewer produces a response; correlation is verified. |
| `PO_HANDOFF_REQUIRED` | Builder | The Reviewer verdict has been captured (or the request timed out with classification). A formal handoff package to the PO is required. | Builder emits a Completion Report to the PO conversation with all required fields. |
| `PO_HANDOFF_CONFIRMED` | PO | The PO has acknowledged receipt of the Completion Report and the contained evidence. | PO Authorization (Next-action authorization) flows back to the Builder. |
| `WAITING_PO_AUTH` | PO | The PO is deciding whether to issue Merge / Ready / Deploy / additional authorization. | PO Authorization executes the action, OR Builder remains halted. |

A transition is only valid if the **source state** was reached through its
single permitted transition and the **target state's owner** has received
the required evidence.

## 3. Handoff Requirements

A formal handoff between Agent and PO requires four artifacts/events:

### 3.1 Completion event

A single, signed, identifiable **completion event** that records:

- the task identifier (Linear issue id)
- the artifact identifier (PR number, branch, HEAD SHA)
- the exact reviewed identifier (PR number, HEAD SHA)
- the timestamp of completion
- the agent identity (who completed it)

This event is recorded into a **persistent task state store** so that a
restart of the Agent process can resume from the last confirmed state.

### 3.2 Notification requirement

The completion event must be delivered to a **shared state / event
channel** that the PO actively monitors. The current implementation routes
through the Neutral Relay to the configured reviewer conversation, but
this is also the channel the PO uses. The notification must:

- not depend on the PO being present in any specific UI
- survive the Agent process terminating
- be readable on a future Agent restart

### 3.3 Acknowledgement requirement

The PO must explicitly acknowledge receipt of the completion event. The
acknowledgement is itself an event:

- received by whom (PO identity)
- when (timestamp)
- what was acknowledged (event identifier)
- next action the PO has authorized (or "no authorization yet")

Until the acknowledgement is recorded, the Builder remains in
`PO_HANDOFF_REQUIRED` and does **not** assume the work has reached the PO.

### 3.4 Ownership of each transition

| Transition | Owner |
|---|---|
| Emit artifact | Builder / Runner |
| Dispatch Review Request | Builder / Runner (via Neutral Relay) |
| Capture correlated Reviewer response | Relay |
| Emit Completion Report to PO | Builder |
| Record PO acknowledgement | PO |
| Decide next action | PO |

The Builder never owns the acknowledgement. The PO never owns the artifact
creation. Each side owns only its side.

## 4. Recovery Model

What happens when the Agent stops before all transitions complete?

### 4.1 Agent process stops

If the Agent process is killed (crash, OOM, machine reboot), the next
restart must be able to:

1. Read the persisted **task state store** to determine the last
   successfully completed transition.
2. Resume from the **next** transition, **not** re-do completed work.
3. Re-verify identity (CDP port, conversation UUID, runtime marker) before
   any new transmission.
4. Re-emit the **Completion Report** if the previous emission was not
   acknowledged.

The Builder must not assume that an emitted artifact implies a
transmitted acknowledgement. The persisted state must distinguish:

- `ARTIFACT_READY` (artifact exists on remote)
- `REVIEW_REQUEST_SENT` (request transmitted)
- `PO_HANDOFF_REQUIRED` (completion report emitted to PO channel)
- `PO_HANDOFF_CONFIRMED` (PO acknowledged)

If only the first two states are recorded, the Builder resumes from
`PO_HANDOFF_REQUIRED` and re-emits the report.

### 4.2 Terminal closes

If the user closes the terminal running the Agent, the Agent process is
typically terminated (SIGTERM). The Agent does not get a chance to emit a
"goodbye" message. Therefore the **Completion Report must be emitted as
soon as each milestone is reached**, not at the very end. The persisted
task state records each milestone.

If the terminal closes mid-execution, the Agent is interrupted. The next
restart reads the persisted state and resumes. The Builder does not lose
work; it loses only time.

### 4.3 Context is lost

If the Agent's conversation / context window is lost (truncation, restart
without persistence), the Builder must:

1. Read the persisted task state.
2. Re-derive **only** the information required for the **next**
   transition from the remote sources of truth (GitHub, Linear, PR,
   Neutral Relay status).
3. Not attempt to re-run completed transitions.

The Builder does not rely on its own memory to know what it did. It
relies on the persisted state and the remote systems.

### 4.4 Reviewer response is delayed

If the Independent Reviewer (GPT reviewer conversation) does not respond
within the bounded wait, the Agent classifies the wait timeout into one
of the documented classes (delivered / not delivered / format mismatch /
identity drift — see AGE-21R). The Agent does **not** assume approval.

The Builder remains in `PO_HANDOFF_REQUIRED` (or in `REVIEW_REQUEST_SENT`
awaiting correlation) and does not transition to `WAITING_PO_AUTH`
without a captured reviewer verdict or an explicit PO authorization.

## 5. Relationship With Existing Governance

The handoff model fits the existing AgentOps governance as follows:

### 5.1 AGE-18 Stop Protocol

AGE-18 governs the **STOP_AND_WAIT** behavior: on drift, ambiguity, or
unverifiable condition, execution halts. The handoff model extends this:
STOP is necessary but not sufficient. STOP is the *halt*, handoff is the
*delivery*. Together they form `STOP_AND_WAIT` plus **notification and
acknowledgement**.

### 5.2 AGE-19 Neutral Relay Hardening

AGE-19 provides the transport layer used by the Builder to emit Review
Requests and Completion Reports. The handoff model does not change the
transport contract (exact conversation identity binding, strict
correlation). It adds: the transport must be used for **both** Review
Request and Completion Report delivery.

### 5.3 AGE-20 Governance Baseline

AGE-20 records the current governance capabilities. The handoff model
extends the baseline with two new explicit roles: **handoff emission**
(by the Builder) and **handoff acknowledgement** (by the PO). Neither
role is automated today; both are required for true unattended long-task
automation.

### 5.4 AGE-21 Long Task Automation Pilot

AGE-21 demonstrated the full governance loop end-to-end. The handoff
model is the formal description of the loop AGE-21 exercised, plus the
gaps that the AGE-21R retrospective identified.

### 5.5 AGE-21R Gap Analysis

AGE-21R is the parent of this document. The four gaps identified
(Report Transport, Authorization Transfer, Task State Persistence,
Recovery Model) are addressed here as the **Handoff Requirements** (3.1
, 3.2, 3.3) and **Recovery Model** (4.1, 4.2, 4.3, 4.4).

## 6. Non Goals (Confirmation)

AGE-22 itself does **not** include:

- any production code change
- any runtime / Neutral Relay / relay_adapter / auth_verifier / CI / config change
- a Runner, Scheduler, Database, or State Service
- a notification system implementation
- changes to authorization rules
- starting AGE-23 or any other future AGE
- any merge or deploy

AGE-22 is a planning record only.

## 7. Final State

This draft is in `WAITING_PO_AUTH` pending PO merge authorization.

The next authorization action is:

> **PO Merge Authorization** for the exact HEAD of this planning document.