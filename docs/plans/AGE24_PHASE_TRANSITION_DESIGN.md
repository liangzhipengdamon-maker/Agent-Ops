# AGE-24 Phase 0.5 — Autonomous Phase Transition Mechanism Design

> Planning-only design document. No production code, no runtime change,
> no merge, no deploy. Continues AGE-24 Phase 0 without entering Phase 1.

## 1. Current Failure Analysis

### 1.1 Observed stop point after Phase 0

The Phase 0 execution (completed after PR #23, HEAD `d826348`) terminated
at the following state:

```
PHASE_COMPLETE (AGE24_PHASE0_COMPLETE)
  ↓
TRANSITION_EVALUATION = (no formal evaluation performed)
  ↓
NEXT_PHASE_READY = false
  ↓
awaiting GPT Web / PO decision for Phase 1 scope
```

The Builder produced a *report* that declared the phase complete, sent the
report through the GPT Relay to the canonical AgentOps reviewer
conversation (CDP 9233, identity-bound `6a74f5c0`), and then **stopped**.

The stop was voluntary. There was no formal guard, no transition policy,
no evaluation function. The Builder chose to stop because:
- It interpreted the completion report as the end of the task.
- It had no durable rule that said "after PHASE_COMPLETE, evaluate
  the next phase and continue until an explicit Human Gate Condition is
  met."
- It treated "report delivered" as equivalent to "handoff acknowledged".

### 1.2 Why the stop is a problem, not a virtue

The host-side requirement is **Overnight Long Task Execution Mode**:

> Do NOT stop after a small task. Do NOT wait for human confirmation. Do
> NOT pause if there is no error. Continue advancing and reporting.

The current local-agent behavior violates that. "Best-effort completion"
becomes a hidden termination. A long-running AI engineering workflow
that pauses at every phase boundary is functionally equivalent to a
short-running one.

### 1.3 Other observed phases that exhibit the same failure

| Phase boundary | Observed stop | Manual intervention required |
|---|---|---|
| AGE-21 Pilot completion | Builder stopped at "WAITING_PO_AUTH" after creating PR #19 | User had to confirm |
| AGE-22 Revision completion | Builder stopped at "WAITING_PO_AUTH" after PR #21 | User had to confirm |
| AGE-22 Rev3 validation completion | Builder stopped at "WAITING_PO_AUTH" after PR #22 | User had to confirm |
| AGE-24 Phase 0 completion | Builder stopped at "PHASE_COMPLETE" pending GPT Web / PO | User (PO/AT) has to reassign next phase |

In every case, the Builder produced a correct report and then voluntarily
halted. The architecture does not include a transition controller.

### 1.4 The minimal missing piece

A Builder needs an explicit **state machine** with at least:

```
TASK_RUNNING
  ↓
PHASE_COMPLETED
  ↓
TRANSITION_EVALUATION
  ↓
NEXT_PHASE_READY
  ↓
TASK_RUNNING            (loop)
```

without a `STOP` between `PHASE_COMPLETED` and `TRANSITION_EVALUATION`.

## 2. State Machine Design

### 2.1 Required states

| State | Owner | Meaning | Permitted transitions |
|---|---|---|---|
| `TASK_RUNNING` | Builder / Agent runtime | A phase is actively executing | → `PHASE_COMPLETED` (via completion detector) |
| `PHASE_COMPLETED` | Builder / Agent runtime | The current phase's deliverable has been produced and reported | → `TRANSITION_EVALUATION` (forced; no STOP allowed) |
| `TRANSITION_EVALUATION` | Transition Controller | The Builder is evaluating the next valid phase | → `NEXT_PHASE_READY` (authorized) \| `HALT_REQUESTED` (human gate triggered) |
| `NEXT_PHASE_READY` | Transition Controller | The next phase is authorized and the next execution state is created | → `TASK_RUNNING` (loop) |
| `WAITING_HUMAN_GATE` | Transition Controller | A Human Gate Condition was triggered; the agent pauses | → `TASK_RUNNING` (PO unblocks) \| `TASK_TERMINATED` (PO cancels) |
| `TASK_TERMINATED` | Transition Controller | Long task ended (PO cancel, fatal error, max-phase reached) | terminal |

### 2.2 Transition rules

- `TASK_RUNNING → PHASE_COMPLETED` is a **local** event of the agent. It
  is triggered by a completion detector that observes the phase's
  required artifact.
- `PHASE_COMPLETED → TRANSITION_EVALUATION` is **forced** and immediate.
  No STOP is allowed between these two states.
- `TRANSITION_EVALUATION → NEXT_PHASE_READY` is authorized by the
  Transition Controller only when:
  - a valid next phase is defined in the phase policy,
  - no Human Gate Condition is currently triggered,
  - the global stop condition (e.g. max-phase, fatal error) is not met.
- `TRANSITION_EVALUATION → WAITING_HUMAN_GATE` is authorized when a
  Human Gate Condition is triggered.
- `NEXT_PHASE_READY → TASK_RUNNING` is the **loop-back** edge. The agent
  re-enters a fresh RUNNING phase with the next-phase state already
  created.

### 2.3 Two-loop mapping

- **Loop A (GPT Web Cognitive Loop)** is the source of *what the next phase
  is*. When uncertainty is human-only (e.g. ambiguous goal, novel
  architecture decision), the Transition Controller must defer to Loop A
  via the GPT Relay, not invent a next phase.
- **Loop B (LoopX Runtime Loop)** persists the state and history of the
  transition. The Transition Controller writes a transition record every
  time `TRANSITION_EVALUATION → NEXT_PHASE_READY` is authorized, so the
  next agent tick can read the persisted state.

### 2.4 Mandatory side effects on every transition

On every `PHASE_COMPLETED → TRANSITION_EVALUATION`:
- Emit a `AGE24_STATUS_REPORT` periodically and on every phase boundary
  (this is the prompt's report format).
- Update the durable state (`.agent-state/task_state.json` and the
  LoopX transition record).
- Push the report to the GPT Web channel via the existing GPT Relay
  (Loop A return path).

## 3. LoopX Mapping

### 3.1 Capability → transition-state mapping

| Transition state | LoopX capability | How it's used |
|---|---|---|
| `TASK_RUNNING` | `loopx refresh-state` | appends execution progress to the active goal state |
| `PHASE_COMPLETED` | `loopx history` (records) | writes a `phase_completed` classification record |
| `TRANSITION_EVALUATION` | reading `ACTIVE_GOAL_STATE.md` + `loopx quota should-run` | bounded decision gate: is the next phase authorized? |
| `NEXT_PHASE_READY` | `loopx refresh-state` (append) + new todo creation | marks the next phase in the registry |
| `WAITING_HUMAN_GATE` | `loopx refresh-state` records `paused_for_gate` | durable pause record |
| `TASK_TERMINATED` | `loopx refresh-state` records `terminated` | durable terminal record |

### 3.2 What LoopX does NOT cover

- LoopX does **not** push to GPT Web. The return path needs the existing
  GPT Relay (Phase 0 finding).
- LoopX does **not** decide the next phase on its own. It requires a
  Transition Controller to call `loopx quota should-run` and interpret
  the result.
- LoopX does **not** evaluate narrative reports. It requires structured
  phase transition records.

### 3.3 What must be AgentOps-only

- **Phase Policy**: definition of valid next phases, pre-conditions, and
  human gate conditions.
- **Transition Controller**: the runtime that observes phase completion
  and drives the transition evaluation.
- **Report Routing**: the Loop A return path (GPT Relay).

## 4. AgentOps Governance Mapping

### 4.1 Transition Controller

The Transition Controller is an AgentOps-governed runtime that:

- observes `PHASE_COMPLETED` events from the Builder
- reads the Phase Policy for the current task
- evaluates whether the next phase is authorized
- triggers a Human Gate Condition if the policy requires it
- writes a transition record to the durable state
- drives the next phase into `TASK_RUNNING`

It does **not** replace Loop A or Loop X. It is the AgentOps layer that
sits between them.

### 4.2 Phase Policy

A Phase Policy for a long task defines:

- the ordered list of valid phases,
- pre-conditions for each phase (what must be true before the next),
- whether the transition is automatic or human-gated,
- the maximum number of phases before a mandatory human gate,
- the allowed retries per phase.

The Phase Policy is a document (not code) that the Transition Controller
loads. It is a planning artifact, not runtime behavior.

### 4.3 Auto Continue Rules

Auto continuation is allowed **only** when:

- a valid next phase is defined in the Phase Policy,
- all pre-conditions for the next phase are met,
- no Human Gate Condition is currently triggered,
- the Builder has not exceeded a bounded retry count for the current phase.

Otherwise, the Transition Controller transitions to `WAITING_HUMAN_GATE`.

### 4.4 Human Gate Conditions

A Human Gate Condition is triggered when:

- the next phase requires a human decision (architecture, scope, risk),
- the Builder has produced a non-trivial failure that the policy cannot
  auto-recover,
- the long task has reached a defined checkpoint (e.g. every N phases,
  or end of a major phase boundary).

When a Human Gate is triggered, the Transition Controller must:

- write a `paused_for_gate` record to the durable state,
- emit a Phase Completion Report explaining the gate condition,
- wait. The Builder does **not** re-attempt the next phase.

### 4.5 Risk-Based Stop Conditions

Risk-based stops are triggered by:

- repeat failures exceeding the bounded retry count for a phase,
- a Transition Controller exception that cannot be classified,
- a deterministic halt by the PO (explicit `TASK_TERMINATED`).

A "stop" in this model is **always** a transition record, not a silent
shutdown.

## 5. Automatic Continuation Rules

The rules in plain text:

1. After producing the phase's required artifact, the Builder MUST
   write `PHASE_COMPLETED` to the durable state.
2. `PHASE_COMPLETED` MUST be followed by `TRANSITION_EVALUATION`. No
   sleep, no wait, no message-output-only transition.
3. `TRANSITION_EVALUATION` applies the Phase Policy:
   - if the next phase is auto-allowed and pre-conditions are met → write
     `NEXT_PHASE_READY` and emit a `TASK_RUNNING` event for the next
     phase.
   - if the next phase requires a human gate → `WAITING_HUMAN_GATE`.
   - if the next phase is undefined or pre-conditions fail →
     `WAITING_HUMAN_GATE` with a clear reason.
4. After `NEXT_PHASE_READY`, the Builder MUST emit a structured
   `AGE24_STATUS_REPORT` and continue into the next phase.
5. The host runtime MUST enforce: between `PHASE_COMPLETED` and
   `TASK_RUNNING(next)`, the only terminal state is
   `WAITING_HUMAN_GATE`. There is no implicit STOP.

## 6. Human Gate Conditions

A phase MUST trigger a Human Gate when:

- the phase policy explicitly marks the transition as human-gated,
- the Builder has retried the phase more than the bounded retry count,
- a non-trivial validator failure occurred (e.g. CI failure that the
  Builder cannot auto-fix without violating a forbidden mutation),
- the next phase requires a Product Owner authorization (e.g. merge,
  deploy, large refactor).

Human Gate payload MUST include:

- the current phase identifier,
- the proposed next phase identifier,
- the reason for the gate,
- the evidence required from the human.

## 7. Recovery Behavior

When the agent is interrupted between transitions:

- on resume, the Builder MUST read the durable state and identify the
  currently-recorded state,
- if the recorded state is `TASK_RUNNING`, continue the current phase,
- if the recorded state is `PHASE_COMPLETED`, drive `TRANSITION_EVALUATION`
  immediately,
- if the recorded state is `WAITING_HUMAN_GATE`, do not start the next
  phase without explicit human input.

The Transition Controller must be designed so that recovery is **idempotent**:
re-running `TRANSITION_EVALUATION` after a crash must produce the same
result as the original run.

## 8. Phase 0.5 → Phase 1 Continuation

After this design document is delivered:

- next phase: **Phase 1 — Brainstorming phase output** (the smallest
  self-transitional phase), which is itself a phase that the
  Transition Controller can drive.
- the next phase artifact will be the Phase 0.5 design document
  (this file) plus a Phase Policy document for AGE-24.
- the Builder will continue automatically to the next valid phase
  unless the policy requires a human gate.

The Host Phase 0.5 task explicitly forbids entering Phase 1 with
implementation. The next phase is **another planning phase**. The
Transition Controller must therefore route the next phase to another
design phase, not an implementation phase.

## 9. Summary

- **Current failure**: the Builder voluntarily stops at `PHASE_COMPLETE`.
- **Required fix**: an explicit Transition Controller that drives
  `PHASE_COMPLETED → TRANSITION_EVALUATION → NEXT_PHASE_READY →
  TASK_RUNNING` without sleeping.
- **LoopX maps** to durable state, history, quota decision, and
  refresh-state.
- **AgentOps adds** the Phase Policy, Transition Controller, and
  Auto Continue Rules.
- **Human gates** are still required for architecture, risk, and
  non-trivial failure paths.
- **No production code change**, no merge, no deploy, no Phase 1
  implementation.

## 10. Next action

Continue to Phase 0.6 (Brainstorming) — another planning phase — by
writing the AGE-24 Phase Policy document and proposing the smallest
next-phase artifact. Emit `AGE24_STATUS_REPORT` with the updated state.
