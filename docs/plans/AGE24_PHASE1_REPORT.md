# AGE-24 Phase 1 Report — LoopX Runtime Validation

> Phase 1: validate LoopX state continuity in real long-task scenarios.
> Local Execution Agent output. Planning-only boundary maintained
> throughout; no production code, no runtime / Neutral Relay / auth /
> CI changes, no merge, no deploy.

## 1. Goal

Validate LoopX native runtime capability across:
- multi-process restart,
- two-agent handoff,
- state persistence,
- recovery.

## 2. Test Workspace

| Field | Value |
|---|---|
| Test project | `/tmp/age24-phase1-test` (separate from Phase 0 `/tmp/age24-loopx-test`) |
| Goal id | `age24-phase1-goal` |
| LoopX runtime | `loopx-canary` v0.4.2 (qualified PASS, AGE-2) |
| Isolated from | AgentOps repo, AgentOps runtime (CDP 9233), main `origin/main` |

## 3. Experiments

### 3.1 Experiment 1 — Bootstrap + state persistence (baseline)

- `loopx-canary bootstrap --project . --goal-id age24-phase1-goal --objective "..." --adapter-kind read_only_project_map_v0 --adapter-status connected-read-only --no-onboarding-scan`
- Result: **PASS**. Wrote `.loopx/registry.json` + `.codex/goals/age24-phase1-goal/ACTIVE_GOAL_STATE.md`; global registry synced.
- Durable state on disk: 2604 bytes ACTIVE_GOAL_STATE.md, schema validated.

### 3.2 Experiment 2 — Two-agent claim conflict

- Registered `agent-1`, then `agent-2`.
- Goal: register both agents in the same project and demonstrate
  exclusive claim enforcement.
- agent-1 acquires lease on `todo_afce128428a0` (120s TTL).
- agent-2 attempts same lease — **rejected** with `error_code: todo_lease_conflict`.
- Verdict: **PASS** — exclusive claim semantics enforced.

### 3.3 Experiment 3 — Two-agent handoff via TTL expiry

- Created a 5-second TTL test todo `todo_74fcb9e8d663`.
- agent-1 acquired lease (TTL 5s).
- agent-2 blocked by `todo_lease_conflict` while lease active.
- After 7s wait, lease shows `expires_at` past.
- agent-2 acquired same lease (version=2, owner=`agent-2`, TTL 30s).
- Verdict: **PASS** — explicit handoff via TTL expiry works; lease file updated atomically.

### 3.4 Experiment 4 — Multi-process restart recovery

- Two separate `loopx-canary status` invocations (simulating process
  restart) read the same state:
  - `global_registry.ok=True`
  - `goal.status=active`
  - lease file (handoff state) preserved: `owner: agent-2`, `version: 2`.
- Verdict: **PASS** — durable state is restart-safe.

### 3.5 Experiment 5 — Refresh-state + run history

- `loopx-canary refresh-state --goal-id age24-phase1-goal --project . --agent-id agent-2`
- Result: `appended: True`, `classification: state_refreshed`, `agent_lane: agent-2`.
- `history` now shows `unique_runs=1`, `records=1`, action recorded.
- Verdict: **PASS** — transition records are auditable.

## 4. Verified capabilities

| Capability | Verified | Evidence |
|---|---|---|
| Durable state | YES | ACTIVE_GOAL_STATE.md + registry.json |
| Goal lifecycle | YES | bootstrap / status / refresh-state all consistent |
| Exclusive claim | YES | agent-1 lease blocks agent-2 with `todo_lease_conflict` |
| Task lease (TTL) | YES | 5s TTL → automatic expiry → agent-2 re-acquire |
| Two-agent handoff | YES | TTL expiry → owner=agent-2, version=2 |
| Multi-process restart | YES | two invocations read consistent state |
| History / run ledger | YES | unique_runs=1, records=1, classification=state_refreshed |
| Recovery (loop-wide) | PARTIAL | restart-safe for state; full CRDT-style recovery not yet tested |

## 5. Findings

### 5.1 LoopX runtime is mature for the handoff lifecycle

The lease + claim + handoff API works as designed (qualifies the AGE-2
PASS experimentally with multi-agent flow). Two agents can take turns
on a single task over time via TTL expiry.

### 5.2 LoopX does not push to GPT Web (confirmed)

The handoff events are recorded in the lease file and the history, but
the GPT Web layer has no built-in notification. The Phase 0.5
Transition Controller must drive the GPT Relay (existing Neutral Relay /
AGE-19) to keep the cognitive loop informed.

### 5.3 Refresh-state records but does not auto-advance

`refresh-state` records the transition but does not push a state
machine forward. It is a checkpoint, not a transition. The Transition
Controller is what reads this state and decides whether to advance to
the next phase.

### 5.4 State file naming is per-goal, not per-task

Each goal has its own `ACTIVE_GOAL_STATE.md`. This is fine for the
multi-project LoopX model but means the Builder must know the goal id
to read state. There is no canonical "current goal" pointer.

## 6. Open questions for Phase 2+

- **Q1**: does the lease survive an OS-level process kill (not just a
  clean exit)? The current test used a clean CLI exit. A real
  `kill -9` would test the on-disk durability invariant more
  aggressively.
- **Q2**: does the Goal State schema fully bind to AgentOps task state?
  We need a mapping convention so Builder can read LoopX and resume its
  own task state.
- **Q3**: how does the Transition Controller read/write both
  `ACTIVE_GOAL_STATE.md` and the `.agent-state/task_state.json` without
  divergence?

## 7. Boundary

- No production code
- No runtime / Neutral Relay / relay_adapter / auth_verifier change
- No merge, no deploy
- No Phase 2 implementation started
- Local Execution Agent role only; GPT Web remains cognitive layer

## 8. Final state

Phase 1 complete. All five experiments passed. Awaiting Phase 2
authorization (next phase per Phase Policy: Phase 2 — Capability mapping
update; auto-allowed).
