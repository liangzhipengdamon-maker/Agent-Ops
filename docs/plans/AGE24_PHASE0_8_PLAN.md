# AGE-24 Phase 0.8 — Minimal Workflow Validation Plan

> Phase 0.8: minimal end-to-end workflow validation plan. Still
> planning-only. No production code. No runtime change. No merge / No
> deploy.

## 1. Goal

Validate the smallest workflow that exercises the dual-loop architecture:

```
GPT Web (Loop A)
  ↓ GPT Relay
  ↓
Local Agent (execution)
  ↓
LoopX (state)
  ↓
AgentOps (governance)
```

without breaking the existing AGE-19 / 5 / 18 / 20 / 22 capabilities.

## 2. Workflow steps (proposed)

1. **GPT Web** creates a minimal task in Linear (the smallest practical
   task that requires a phase transition).
2. **GPT Relay** sends the task description to the isolated AgentOps
   runtime (CDP 9233).
3. **Local Agent** bootstraps a LoopX goal for the task, writes the
   artifact, transitions through `PHASE_COMPLETED`.
4. **Transition Controller** evaluates the next phase per the Phase Policy.
   Since the human gate for Phase 1 is not yet triggered, the Controller
   auto-continues.
5. **GPT Relay** pushes the `AGE24_STATUS_REPORT` to the canonical
   conversation.
6. **GPT Web** records the decision and the next instruction.

## 3. Required pre-conditions

- The Transition Controller design (Phase 0.5) is approved.
- The Phase Policy (Phase 0.6) is approved.
- The integration architecture (Phase 0.7) is approved.
- A human gate is allowed between Phase 0.8 and Phase 1.

## 4. Validation criteria

- the workflow passes through the full state machine
  (`TASK_RUNNING → PHASE_COMPLETED → TRANSITION_EVALUATION →
  NEXT_PHASE_READY → TASK_RUNNING`) without silent STOP,
- the LoopX state machine records the transition history,
- the AgentOps `.agent-state/task_state.json` records the new phase,
- the GPT Relay pushes the status report to the canonical conversation,
- the Builder does not stop at `PHASE_COMPLETE` without an explicit
  human gate.

## 5. Boundary

- No production code in Phase 0.8.
- No runtime change.
- No merge, no deploy.

No human gate required for Phase 0.8 itself; a human gate is required
to proceed to Phase 1 implementation.

## 6. After Phase 0.8

Phase 0.8 is the last planning phase. The next step is a human gate that
decides whether to proceed to Phase 1 (run LoopX locally with multi-process
restart + two-agent handoff).
