# AGE-24 Phase Policy

> Phase Policy document for the AGE-24 Transition Controller.
> Per the Phase 0.5 design, the Transition Controller loads this document
> to decide whether a next phase is authorized and whether a human gate is
> required. No production code, no runtime change, no merge, no deploy.

## 1. Phases

| Phase | Goal | Auto-allowed? | Human gate required? | Output artifact |
|---|---|---|---|---|
| Phase 0 | Goal alignment + LoopX bootstrap + capability mapping | yes | no | docs/plans/AGE24_PHASE0_COMPLETION_REPORT.md |
| Phase 0.5 | Autonomous Phase Transition mechanism design | yes | no | docs/plans/AGE24_PHASE_TRANSITION_DESIGN.md |
| Phase 0.6 | Brainstorming: enumerate candidate next phases (planning only) | yes | no | docs/plans/AGE24_PHASE0_6_BRAINSTORM.md |
| Phase 0.7 | Integration architecture design (planning, no code) | yes | no | docs/plans/AGE24_PHASE0_7_INTEGRATION.md |
| Phase 0.8 | Minimal workflow validation plan (planning, no code) | yes | no | docs/plans/AGE24_PHASE0_8_PLAN.md |
| Phase 1 | Run LoopX locally (multi-process restart + two-agent handoff) | yes | no (env-list) | runtime setup record |
| Phase 2 | Capability mapping update | yes | no | capability matrix |
| Phase 3 | AgentOps integration design | yes | **yes** | integration architecture |
| Phase 4 | Integration prototype (no production code) | yes | **yes** | minimal prototype |
| Phase 5 | Production validation (AI-Investment-Lab, not immediate) | **yes** | **yes** | validation report |
| Phase 6 | Final production framework | yes | **yes** | final framework |

## 2. Pre-conditions (per phase)

| Phase | Pre-conditions (must be present in durable state) |
|---|---|
| Phase 0 | (none) |
| Phase 0.5 | `TASK_RUNNING: PHASE_0` + `ARTIFACT_READY: docs/plans/AGE24_PHASE0_COMPLETION_REPORT.md` |
| Phase 0.6 | `TASK_RUNNING: PHASE_0.5` + `ARTIFACT_READY: docs/plans/AGE24_PHASE_TRANSITION_DESIGN.md` |
| Phase 0.7 | `TASK_RUNNING: PHASE_0.6` + `ARTIFACT_READY: docs/plans/AGE24_PHASE0_6_BRAINSTORM.md` |
| Phase 0.8 | `TASK_RUNNING: PHASE_0.7` + `ARTIFACT_READY: docs/plans/AGE24_PHASE0_7_INTEGRATION.md` |
| Phase 1 | Phase 0.8 human gate passed (or explicitly auto-allowed) |
| Phase 2 | Phase 1 completed |
| Phase 3 | Phase 2 completed |
| Phase 4 | Phase 3 human gate passed |
| Phase 5 | Phase 4 completed |
| Phase 6 | Phase 5 completed |

## 3. Human Gate Conditions

A human gate is triggered when:

- **Phase 3, 4, 5, 6**: integration / production actions require explicit
  Product Owner authorization.
- any phase where the retry count exceeds the bounded retry count (default 1).
- any phase where the next-phase pre-condition cannot be verified
  automatically (e.g. requires a specific GitHub / Linear state the agent
  cannot read with confidence).

## 4. Risks

Known risks for the current phase (Phase 0.6):

- none for Phase 0.6 itself (planning-only).
- downstream risk: Phase 3/4/5/6 require human gates; the Builder must
  not auto-continue past them.

## 5. Auto-Continue Rules

Apply per phase, in this order:

1. If `PHASE_COMPLETED` is recorded and the pre-conditions for the next
   phase are met and the next phase is auto-allowed → drive
   `TRANSITION_EVALUATION → NEXT_PHASE_READY → TASK_RUNNING`.
2. If a human gate is required for the next phase → write
   `paused_for_gate` and stop at `WAITING_HUMAN_GATE`.
3. If the next phase is undefined or pre-conditions fail → write
   `paused_for_unknown_next` and stop at `WAITING_HUMAN_GATE`.

## 6. Transition Controller Authority

The Phase Policy is read-only for the runtime. Only the **Planning +
Cognitive layer** (GPT Web) can edit it. The Builder reads it but does
not modify it.

## 7. Recovery Behavior

On restart, the Controller reads the durable state and resumes at the
last known transition. If the recorded state is `PAUSED_FOR_GATE`, the
Controller does **not** attempt the next phase.
