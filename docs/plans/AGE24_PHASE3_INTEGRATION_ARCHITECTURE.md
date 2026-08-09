# AGE-24 Phase 3 — Integration Architecture

> Design for combining the GPT Web Cognitive Loop, the LoopX State Loop,
> and the AgentOps Governance Loop. Planning-only. No code.

## 1. Confirmed facts (Phase 0-2)

LoopX provides:
- state (`.loopx/registry.json`, `ACTIVE_GOAL_STATE.md`)
- claim (`todo --bound-agent / --claimed-by`)
- lease (`task-lease` with TTL)
- handoff (TTL expiry → owner transfer)
- history (`history`, `evidence-log`)
- refresh-state (checkpoint)

LoopX does NOT provide:
- GPT Web push
- auto-advance (phase transition)

AgentOps provides:
- authorization verifier (AGE-5)
- stop protocol + ACK (AGE-18)
- Neutral Relay transport on isolated runtime (AGE-19)
- governance baseline (AGE-20)
- handoff completion contract design (AGE-22)
- PO handoff delivery **NOT implemented** (AGE-22 validation)

## 2. Architectural Context

```
┌─────────────────────────────────────────────────────┐
│  GPT Web  (Cognitive Loop A)                        │
│  architecture / reasoning / review / decisions      │
└───────────────┬─────────────────────────────────────┘
                │ GPT Relay (Neutral Relay, AGE-19)
                ▼
┌─────────────────────────────────────────────────────┐
│  Transition Controller (AgentOps Governance Loop)   │
│  - phase evaluation                                 │
│  - Phase Policy Engine                              │
│  - human gate + auto continue                       │
│  - state ownership                                 │
└───────┬───────────────────────────┬─────────────────┘
        │ reads/writes              │ transport (report)
        ▼                           ▼
┌────────────────────┐   ┌──────────────────────────┐
│ LoopX State Loop B │   │ Local Execution Agent    │
│ durable state      │   │ (Claude Code / OpenCode) │
│ claim/lease/history│   └──────────────────────────┘
└────────────────────┘
```

Three loops, three responsibilities:

- **Loop A (GPT Web)**: cognition, decisions, review.
- **Loop B (LoopX)**: durable state, claims, leases, history, memory.
- **AgentOps Governance Loop**: authorization, evidence, phase
  transitions, human gates, report routing.

## 3. Transition Controller Architecture

### 3.1 Responsibilities

- Watch for `PHASE_COMPLETED` events.
- Evaluate the next phase using the Phase Policy Engine.
- Route the transition: auto-advance or human gate.
- Write the transition record to LoopX (history) and AgentOps
  (`.agent-state/task_state.json`).
- Push the phase report to GPT Web via the Neutral Relay.

### 3.2 Placement

The Transition Controller is **not** a daemon. It is a **runtime step** the
Local Agent runs at each phase boundary:

```
Local Agent completes phase
  ↓
Local Agent invokes Transition Controller step
  ↓
step reads Phase Policy
  ↓
step reads LoopX state
  ↓
step evaluates next phase (auto vs gate)
  ↓
step writes transition record
  ↓
step returns next phase to Local Agent
```

This keeps the design faithful to "one bounded action per wake" and avoids
introducing a scheduler/daemon (explicitly forbidden).

### 3.3 Inputs / Outputs

| Input | Source |
|---|---|
| Phase Policy | `docs/plans/AGE24_PHASE_POLICY.md` (GPT Web authored) |
| Current phase state | LoopX `ACTIVE_GOAL_STATE.md` |
| Agent task state | `.agent-state/task_state.json` |
| PR/HEAD binding | `.agent-bridge/status.json` |

| Output | Target |
|---|---|
| Transition record | LoopX `history` |
| Next phase | Local Agent (return value) |
| Phase report | GPT Relay → GPT Web conversation |

## 4. Phase Policy Engine

### 4.1 Schema (conceptual)

A Phase Policy entry:

```yaml
phase:
  id: Phase-3
  name: Integration architecture design
  auto_allowed: false        # Phase 3 was human-gated
  human_gate_reason: integration_requires_owner_decision
  preconditions:
    - artifact: docs/plans/AGE24_PHASE2_CAPABILITY_MAPPING.md
    - state: ACTIVE_GOAL_STATE.md present
  retry_limit: 1
```

### 4.2 Evaluation

The engine returns one of:

- `AUTO_ADVANCE` — next phase auto-allowed, preconditions met.
- `HUMAN_GATE` — next phase human-gated OR preconditions not verifiable.
- `TERMINATE` — no next phase defined or PO terminated.

### 4.3 Where the engine runs

The Phase Policy Engine is a **pure decision function** the Transition
Controller step invokes. It reads the policy file + current state and
returns a decision. No runtime service, no scheduler, no database.

## 5. GPT Relay Integration Boundary

### 5.1 The boundary

- **GPT Relay (Neutral Relay, AGE-19)** is the ONLY transport to GPT Web.
- The Transition Controller must NOT call GPT Web directly.
- All phase status reports go through the Neutral Relay on the isolated
  AgentOps runtime (CDP 9233, profile `~/.agentops/chrome-profile`,
  marker `AgentOps-9233`).

### 5.2 Report contract (inherited from AGE-18)

```
REVIEW_REQUEST_ID: <uuid>
REPO: <exact repo>
PR: <exact PR>
HEAD: <exact reviewed HEAD>
REQUEST: status_report
STATE: <phase state>
SUMMARY: <structured phase summary>
UNAUTHORIZED_ACTIONS: NONE|<list>
```

### 5.3 Strict correlation (AGE-19)

The report must bind REVIEW_REQUEST_ID / REPO / PR / HEAD exactly. The
Transition Controller reads the relay output file and validates the
binding before recording `REPORT_DELIVERED`.

## 6. State Ownership Model

| State | Owner | Written by | Read by |
|---|---|---|---|
| Phase Policy | GPT Web (cognitive) | GPT Web | Transition Controller |
| Phase state (goal) | LoopX | Local Agent (via `refresh-state`) | Transition Controller |
| Agent task state | AgentOps (local) | Local Agent | Transition Controller |
| PR/HEAD binding | AgentOps | Builder | Transition Controller |
| Transition record | LoopX | Transition Controller | Recovery |
| Phase report | AgentOps | Local Agent | GPT Web |

Rules:

- No cross-writing: GPT Web only edits policy; LoopX only stores goal
  state; AgentOps owns the task/PR state.
- The Transition Controller is the only writer of transition records.
- State divergence is prevented by reading one canonical source per
  field (policy → policy file; phase → LoopX; task → task_state.json;
  PR → status.json).

## 7. Human Gate Conditions

A human gate is triggered (the Controller returns `HUMAN_GATE`) when:

1. The next phase is marked `auto_allowed: false` in the Phase Policy.
2. A precondition cannot be verified automatically.
3. The phase retry limit is exceeded.
4. A non-trivial validator failure occurred.
5. The phase requires a Product Owner authorization (merge, deploy,
   production integration).

Human gate payload:

```
current_phase: <id>
next_phase: <id>
reason: <gate reason>
evidence: <required evidence from human>
```

## 8. Auto Continue Rules

The Controller auto-advances (`AUTO_ADVANCE`) only when:

1. The next phase is `auto_allowed: true`.
2. All preconditions verified against LoopX + task state.
3. Retry count within limit.
4. No human-gate condition triggered.

Auto-advance produces a new `TASK_RUNNING` for the next phase and records
the transition.

## 9. State Lifecycle (final)

```
TASK_RUNNING
   ↓ PHASE_COMPLETED
TRANSITION_EVALUATION
   ↓ AUTO_ADVANCE (policy)
NEXT_PHASE_READY
   ↓
TASK_RUNNING (next)
        ↕
   HUMANGATE → WAITING_HUMAN_GATE → (PO unblocks) → TASK_RUNNING
        ↕
   TERMINATE → TASK_TERMINATED
```

## 10. Phase 3 → Phase 4 boundary

Phase 4 (minimal integration prototype) requires a **human gate** per the
Phase Policy. This architecture design is the last design-only phase
before any prototype.

## 11. Boundary

- No production code
- No runtime / Neutral Relay / relay_adapter / auth_verifier change
- No scheduler / daemon / database / state service
- No merge, no deploy
- No Phase 4 implementation started
- Local Execution Agent role only; GPT Web remains cognitive layer
