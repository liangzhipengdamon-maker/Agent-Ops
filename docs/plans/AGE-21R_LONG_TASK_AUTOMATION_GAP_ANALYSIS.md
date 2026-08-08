# AGE-21R Long Task Automation Gap Analysis

> Planning-only governance gap analysis.
> Derived from the AGE-21 Long Task Automation Pilot.
> This document analyzes manual intervention points and required future
> capabilities. It does **not** implement automation.

## Governance Principle

> **A governance state transition requires a confirmed handoff.**
>
> Prompt behavior is not the control mechanism.
> Governance rules are the control mechanism.
>
> This document does **not** define completion as "the agent should remember
> to send a message". Completion is defined as the successful traversal of a
> formal handoff contract with evidence at each transition.

## PO Handoff Completion Contract

A task is **not complete** at any of the following points alone:

- artifact created
- PR created
- Review Request sent

A task is complete only when the **PO Handoff Completion Contract** is
satisfied, which requires three explicit outputs.

### Contract Output 1 — Completion Artifact

After `EXECUTION_COMPLETE`, the Builder emits a **Completion Artifact**
containing:

| Field | Required | Notes |
|---|---|---|
| Task ID | yes | Linear identifier |
| Repository | yes | canonical repository name |
| Branch | yes | exact branch name |
| Commit SHA | yes | exact reviewed commit SHA |
| Changed files | yes | list of paths changed in this task |
| Validation results | yes | local checks + CI status |

### Contract Output 2 — Review Handoff

After `ARTIFACT_READY`, the Builder dispatches a **Review Handoff**
through the Neutral Relay on the isolated AgentOps runtime, containing:

| Field | Required | Notes |
|---|---|---|
| Review Request ID | yes | unique per task |
| Reviewer target | yes | exact conversation UUID bound to expected reviewer |
| Review status | yes | sent / captured / timed-out (classified) |
| Correlation information | yes | request_id / repo / PR / HEAD binding, strict single-line format expected |

### Contract Output 3 — PO Handoff

After `REVIEW_REQUEST_SENT`, the Builder emits a **PO Handoff** to the
controlling PO channel.

#### When PO notification is required

PO notification is required whenever the Builder reaches
`PO_HANDOFF_REQUIRED`. This is **not optional** and **not dependent on
prompt behavior** — it is a governance state transition.

#### What information must be delivered

The PO Handoff must contain:

- the Completion Artifact (Contract Output 1)
- the Review Handoff result (Contract Output 2)
- the current governance state (from the lifecycle below)
- the next authorization action required from the PO
- the exact identifier the PO must reference when authorizing (PR number,
  HEAD SHA)

#### How acknowledgement is represented

Acknowledgement is itself an event, recorded as
`PO_HANDOFF_CONFIRMED`. Until the acknowledgement is recorded, the
Builder remains in `PO_HANDOFF_REQUIRED` and does not transition to
`WAITING_PO_AUTH`. The acknowledgement must carry:

- PO identity (who acknowledged)
- timestamp
- which completion event is acknowledged (Linear task id + PR + HEAD)
- whether any next-action authorization is included (or "no authorization
  yet")

## State Transition Requirement

The lifecycle of a completed task is exactly:

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

Each transition has a **single owner** and a **single permitted
transition rule**. Transitions out of order are not valid.

| State | Owner | Transition out |
|---|---|---|
| `EXECUTION_COMPLETE` | Builder | emit Completion Artifact → `ARTIFACT_READY` |
| `ARTIFACT_READY` | Builder | dispatch Review Handoff via Neutral Relay → `REVIEW_REQUEST_SENT` |
| `REVIEW_REQUEST_SENT` | Builder | classify response, emit PO Handoff → `PO_HANDOFF_REQUIRED` |
| `PO_HANDOFF_REQUIRED` | Builder | (wait) |
| `PO_HANDOFF_CONFIRMED` | PO | record acknowledgement → `WAITING_PO_AUTH` |
| `WAITING_PO_AUTH` | PO | issue Next-action authorization (or stay halted) |

The Builder never owns a state transition owned by the PO. The PO never
owns a state transition owned by the Builder. Either side acting outside
its ownership is a governance violation.

## Failure Handling

The PO Handoff Completion Contract must define behavior under four
failure classes. The Builder **must not** silently assume success or
default to "complete" on any of these.

### Reviewer response is delayed

- Classify the wait timeout into one of:
  - request delivered, response pending
  - request delivered, response present, format mismatch
  - request not delivered
  - conversation identity drift during wait
- Do **not** assume approval.
- Remain in `REVIEW_REQUEST_SENT` until either correlation succeeds or
  the response is classified.
- If the response is in narrative format (not strict single-line ACK),
  do **not** weaken the strict correlation contract. Record the
  classification and surface it in the PO Handoff so the PO can decide.

### PO notification fails

- If the Neutral Relay transport fails for the PO Handoff emission, the
  Builder does **not** assume the PO received it.
- Classify the failure (transport unavailable / identity drift / response
  timeout) and persist the state.
- The Builder may retry the emission within bounded limits if identity
  binding is preserved. If retries exhaust, the Builder transitions to
  `PO_HANDOFF_REQUIRED` and remains there until either a new emission
  succeeds or the PO surfaces themselves.

### Agent process terminates

- Persist the last successfully completed state into a task-state store
  before the Agent exits, if possible.
- On restart, read the persisted state and resume from the **next**
  transition, **not** re-do completed work.
- If the Agent was killed before persistence (hard crash), the next
  restart must re-derive the state from remote sources of truth (GitHub,
  Linear, PR, Neutral Relay status) and identify the highest
  successfully reached state before resuming.

### Context is lost

- Do not rely on conversation history or context-window memory to know
  what was done.
- Re-derive the last known state from remote sources of truth.
- Re-emit the PO Handoff if the previous emission was not
  acknowledged.
- Never assume a prior transition completed based on memory alone.

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
governance transition. The PO Handoff Completion Contract (above)
defines what that handoff must produce.

## 2. Governance State Model

The state transition requirement (see "State Transition Requirement"
above) is the authoritative lifecycle. The table below is the
operational view.

| State | Owner | Meaning | Transition |
|---|---|---|---|
| `EXECUTION_COMPLETE` | Builder / Runner | All planned actions for the task have been performed locally. | Builder emits a Completion Artifact (Contract Output 1). |
| `ARTIFACT_READY` | Builder / Runner | The Completion Artifact exists on the remote and the exact identifier (PR number, branch, HEAD SHA) is known. | Builder dispatches a Review Handoff (Contract Output 2) through the Neutral Relay. |
| `REVIEW_REQUEST_SENT` | Relay | The Review Request has been transmitted to the configured reviewer conversation. Identity-binding diagnostics confirm. | Reviewer produces a response; correlation is verified. |
| `PO_HANDOFF_REQUIRED` | Builder | The Reviewer verdict has been captured (or the request timed out with classification). A formal PO Handoff (Contract Output 3) is required. | Builder emits the PO Handoff to the PO channel. |
| `PO_HANDOFF_CONFIRMED` | PO | The PO has acknowledged receipt of the PO Handoff. | PO Authorization (Next-action authorization) flows back to the Builder. |
| `WAITING_PO_AUTH` | PO | The PO is deciding whether to issue Merge / Ready / Deploy / additional authorization. | PO Authorization executes the action, OR Builder remains halted. |

A transition is only valid if the **source state** was reached through its
single permitted transition and the **target state's owner** has received
the required evidence.

## 3. Handoff Requirements (Contract Outputs)

### 3.1 Completion Artifact (Contract Output 1)

Required fields:

- Task ID
- Repository
- Branch
- Commit SHA
- Changed files
- Validation results

### 3.2 Review Handoff (Contract Output 2)

- Review Request ID
- Reviewer target
- Review status (sent / captured / timed-out, classified)
- Correlation information

### 3.3 PO Handoff (Contract Output 3)

When PO notification is required, what information must be delivered,
and how acknowledgement is represented — see **PO Handoff Completion
Contract** above.

### 3.4 Ownership of each transition

The Builder never owns acknowledgement. The PO never owns artifact
creation. Each side owns only its side.

## 4. Recovery Model

### 4.1 Agent process terminates

See "Failure Handling — Agent process terminates" above.

### 4.2 Terminal closes

If the user closes the terminal running the Agent, the Agent process is
typically terminated (SIGTERM). The Agent does not get a chance to emit
a "goodbye" message. Therefore the **Completion Artifact and PO Handoff
must be emitted as soon as each milestone is reached**, not at the very
end. The persisted task state records each milestone.

If the terminal closes mid-execution, the Agent is interrupted. The next
restart reads the persisted state and resumes. The Builder does not
lose work; it loses only time.

### 4.3 Context is lost

See "Failure Handling — Context is lost" above.

### 4.4 Reviewer response is delayed

See "Failure Handling — Reviewer response is delayed" above. The Builder
does not transition to `WAITING_PO_AUTH` without a captured reviewer
verdict or an explicit PO authorization.

## 5. Relationship With Existing Governance

The handoff model fits the existing AgentOps governance as follows.

### 5.1 AGE-18 Stop Protocol

AGE-18 governs the **STOP_AND_WAIT** behavior: on drift, ambiguity, or
unverifiable condition, execution halts. The PO Handoff Completion
Contract extends this: STOP is necessary but not sufficient. STOP is the
*halt*, handoff is the *delivery*.

### 5.2 AGE-19 Neutral Relay Hardening

AGE-19 provides the transport layer used by the Builder to emit Review
Handoffs and PO Handoffs. The PO Handoff Completion Contract does not
change the transport contract (exact conversation identity binding,
strict correlation). It adds: the transport must be used for **both**
Review Handoff and PO Handoff emission.

### 5.3 AGE-20 Governance Baseline

AGE-20 records the current governance capabilities. The PO Handoff
Completion Contract extends the baseline with two new explicit roles:
**handoff emission** (by the Builder) and **handoff acknowledgement**
(by the PO). Neither role is automated today; both are required for
true unattended long-task automation.

### 5.4 AGE-21 Long Task Automation Pilot

AGE-21 demonstrated the full governance loop end-to-end. The PO Handoff
Completion Contract is the formal description of the loop AGE-21
exercised, plus the gaps that the AGE-21R retrospective identified.

### 5.5 AGE-21R Gap Analysis

AGE-21R is the parent of this document. The four gaps identified
(Report Transport, Authorization Transfer, Task State Persistence,
Recovery Model) are addressed here as the **Contract Outputs** (3.1,
3.2, 3.3), **Recovery Model** (4.1, 4.2, 4.3, 4.4), and **Failure
Handling** (Reviewer delayed / PO notification fails / Agent terminates /
Context lost).

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