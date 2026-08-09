# AGE-24 Phase 0.7 — Integration Architecture Design

> Phase 0.7: integration architecture between AgentOps, LoopX, and the
> GPT Web cognitive loop. Planning-only. No production code. No merge.
> No deploy.

## 1. Current responsibilities

| Layer | Owns | Today |
|---|---|---|
| **Loop A — GPT Web** | architecture, reasoning, decisions, review | active (PO uses ChatGPT) |
| **GPT Relay / Neutral Relay** | transport between GPT Web and Local Agent | active (AGE-19, CDP 9233 isolated runtime) |
| **LoopX** | durable state, leases, history, decision gate | qualified PASS (AGE-2); bootstrapped in Phase 0 |
| **Local Agent** | execution, reports, artifacts | active (Claude Code / OpenCode) |
| **AgentOps** | authorization, evidence, review, stop protocol | active (AGE-5, AGE-18, AGE-20) |

## 2. Proposed integration boundary

**Where LoopX state lives**
- Per-project: `<project>/.loopx/registry.json` + `<project>/.codex/goals/<goal-id>/ACTIVE_GOAL_STATE.md`
- Global: `~/.codex/loopx/registry.global.json`

**Where AgentOps state lives** (today)
- `.agent-bridge/status.json` (PR/HEAD/state/episode)
- `.agent-state/` (local-only state, per the Latest pilot prompt)

**Where the Transition Controller reads from**
- LoopX `ACTIVE_GOAL_STATE.md` (durable phase/task state)
- AgentOps `.agent-state/task_state.json` (local agent state)
- `.agent-bridge/status.json` (PR/HEAD binding)

**Where the GPT Relay pushes**
- The canonical GPT Web conversation (AgentOps reviewer session,
  `6a74f5c0-a240-83ec-9cff-198ffab1140e`)

**Where the Transition Controller writes**
- LoopX registration (transition record)
- AgentOps `.agent-state/task_state.json` (local state)
- GPT Relay (status report)

## 3. Sequence diagrams (textual)

### 3.1 Phase completion → next phase (automatic)

```
Builder (TASK_RUNNING)
  ↓ produces phase artifact
PHASE_COMPLETED
  ↓
Transition Controller
  ↓ reads Phase Policy
  ↓ reads LoopX state
  ↓ verifies next-phase pre-conditions
NEXT_PHASE_READY (auto-allowed)
  ↓ writes transition record (LoopX)
  ↓ updates .agent-state/task_state.json
  ↓ emits AGE24_STATUS_REPORT (GPT Relay)
TASK_RUNNING(next phase)
```

### 3.2 Phase completion → human gate

```
Builder (TASK_RUNNING)
  ↓ produces phase artifact
PHASE_COMPLETED
  ↓
Transition Controller
  ↓ reads Phase Policy
  ↓ recognizes human gate for next phase
WAITING_HUMAN_GATE
  ↓ writes paused_for_gate (LoopX)
  ↓ emits Phase Completion Report explaining gate
  ↓ stop
```

### 3.3 Recovery after interruption

```
Agent wake
  ↓ reads durable state
  ↓ identifies current state
  ↓ if TASK_RUNNING → continue current phase
  ↓ if PHASE_COMPLETED → drive TRANSITION_EVALUATION now
  ↓ if NEXT_PHASE_READY → continue next phase
  ↓ if WAITING_HUMAN_GATE → wait (do not proceed)
```

## 4. State ownership matrix

| State | Owner | Reducer |
|---|---|---|
| Phase policy | GPT Web (read-only) | GPT Web (write) |
| Phase state (current/in-progress) | LoopX (`ACTIVE_GOAL_STATE.md`) | Transition Controller |
| Local agent task state | `.agent-state/task_state.json` | Local Agent |
| Phase transition record | LoopX (`history`) | Transition Controller |
| Status report | GPT Relay output | Local Agent |
| PR/HEAD binding | `.agent-bridge/status.json` | Builder (via relay_adapter) |
| Human gate record | LoopX (`history`) | Transition Controller |

## 5. Failure modes + recovery

| Failure | Detection | Recovery |
|---|---|---|
| Phase artifact missing | pre-condition check fails | enter `WAITING_HUMAN_GATE` with reason |
| LoopX unavailable | bootstrap failure | enter `WAITING_HUMAN_GATE` with reason (cannot read state) |
| GPT Relay unavailable | report cannot push | state still recorded; retry on next heartbeat; do not lose state |
| Agent process crashes | durable state present | restart reads state, resumes at `TASK_RUNNING` of the current phase |
| Decision history corrupted | history read fails | fall back to last good record; surface discrepancy |

## 6. Open questions requiring GPT Web decision

- **Q1**: should the Transition Controller itself be a LoopX goal
  (sub-goal) or an AgentOps-level runtime entity?
- **Q2**: should the `.agent-state/` directory be migrated into LoopX
  state, or kept as a separate AgentOps cache?
- **Q3**: who is the policy author — GPT Web only, or can the Builder
  propose amendments?
- **Q4**: what is the bounded retry count per phase? Default 1, but
  phases with reversible failures (e.g. validator re-runs) may need more.

## 7. Boundary

- No production code
- No runtime / Neutral Relay / relay_adapter / auth_verifier change
- No merge, no deploy
- No human gate required for this phase (per Phase Policy: Phase 0.7 is
  auto-allowed)

## 8. Next phase

After Phase 0.7: Phase 0.8 — Minimal workflow validation plan (planning).
Then human gate before Phase 1.
