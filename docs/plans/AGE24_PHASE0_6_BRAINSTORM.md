# AGE-24 Phase 0.6 — Brainstorm

> Phase 0.6 Brainstorm: enumerate candidate next phases after Phase 0.5.
> Planning-only. No production code. No runtime change. No merge/No
> deploy.

## 1. Question

Given the Phase 0.5 Transition Controller design and the Phase Policy, what
are the candidate next phases for AGE-24?

## 2. Candidate Brainstorm

| Candidate | Auto-allowed? | Human gate? | Output size | Notes |
|---|---|---|---|---|
| **Phase 0.7 — Integration architecture design** | yes | no | small | concrete architecture diagram (textual) |
| Phase 1 — Run LoopX locally (multi-process restart + two-agent handoff) | yes | no | medium | continues Phase 0 bootstrap work; needs test harness |
| Phase 1B — AgentOps↔LoopX state schema mapping | yes | no | small | defines the schema mapping |
| Phase 2 — Capability matrix update | yes | no | small | updates the AGE-24 capability matrix |
| Phase 3 — Integration design (production) | no | **yes** | medium | architecture + governance decisions |
| Phase 4 — Minimal prototype | no | **yes** | large | requires human sign-off |

## 3. Recommended next phase

**Phase 0.7 — Integration architecture design** (planning, no code).

**Rationale**: the Transition Controller design and the Phase Policy agree
that the next useful work is the architectural integration between
AgentOps and LoopX. This requires a concrete design (textual diagrams +
interfaces) before any implementation. The smallest phase that produces a
real artifact is the integration architecture design.

## 4. Phase 0.7 — Integration Architecture Design (proposed)

**Output**: `docs/plans/AGE24_PHASE0_7_INTEGRATION.md`

**Sections**:
1. Current responsibilities (Loop A / Loop B / AgentOps).
2. Proposed integration boundary (where LoopX state is stored, where
   the GPT Relay pushes, where the Transition Controller reads).
3. Sequence diagrams (textual) for the dual-loop architecture.
4. State ownership matrix: who owns `ACTIVE_GOAL_STATE.md`, who owns
   the `.agent-bridge/status.json`, who owns the `AGE24_STATUS_REPORT`.
5. Failure modes + recovery paths.
6. Open questions requiring GPT Web decision.

**Boundary**: no code, no merge, no deploy.

## 5. After Phase 0.7

Phase 0.8 — Minimal workflow validation plan (planning). Then human
gate before Phase 1.
