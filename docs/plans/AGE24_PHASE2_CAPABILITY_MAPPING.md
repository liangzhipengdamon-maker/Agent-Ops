# AGE-24 Phase 2 — Capability Mapping Update

> Phase 2: update the AGE-24 capability matrix with Phase 1 runtime
> evidence. Planning-only. No production code, no runtime change, no
> merge, no deploy.

## 1. Purpose

The Phase 0 capability map was based on the AGE-2 qualification report and
a single bootstrap run. Phase 1 added real multi-agent runtime evidence
(lease conflict, TTL handoff, restart recovery, refresh-state). This
document updates the capability matrix accordingly.

## 2. Updated Capability Matrix

### 2.1 LoopX capabilities (verified)

| Capability | Phase 0 verdict | Phase 1 evidence | Updated verdict |
|---|---|---|---|
| Durable state | PASS (bootstrap) | ACTIVE_GOAL_STATE.md + registry persisted; 2nd invocation reads same state | **CONFIRMED** |
| Goal lifecycle | PASS | bootstrap / status / refresh-state all consistent | **CONFIRMED** |
| Exclusive claim | PASS (AGE-2) | agent-1 lease blocks agent-2 (`todo_lease_conflict`) | **CONFIRMED** (multi-agent) |
| Task lease TTL | PASS (AGE-2) | 5s TTL → automatic expiry → agent-2 re-acquire | **CONFIRMED** |
| Two-agent handoff | PASS (AGE-2) | TTL expiry → owner=agent-2, version=2 | **CONFIRMED** (live) |
| Multi-process restart | PASS (AGE-2) | two invocations read consistent state; lease preserved | **CONFIRMED** (live) |
| History / run ledger | PASS | unique_runs=1, records=1, classification=state_refreshed | **CONFIRMED** |
| Refresh-state | PASS | appended, agent_lane recorded | **CONFIRMED** |
| Recovery | PARTIAL | restart-safe; `kill -9` not yet tested | **PARTIAL** (needs kill test) |
| GPT Web push | **NOT PROVIDED** | no push to GPT Web | **NOT PROVIDED** (Transition Controller + GPT Relay required) |
| Auto-advance | **NOT PROVIDED** | refresh-state is a checkpoint, not a transition | **NOT PROVIDED** (Transition Controller required) |

### 2.2 AgentOps capabilities (current)

| Capability | Status | Source |
|---|---|---|
| Authorization verifier | Complete | AGE-5 |
| Stop protocol (auto-report + ACK) | Complete | AGE-18 |
| Neutral Relay transport (isolated runtime) | Complete | AGE-19 |
| Governance baseline | Complete | AGE-20 |
| Completion handoff contract (design) | Design only | AGE-22 |
| PO handoff delivery | **NOT IMPLEMENTED** | AGE-22 validation |
| Transition Controller | **Design only** | AGE-24 Phase 0.5 |
| Phase Policy | **Design only** | AGE-24 Phase 0.6 |
| Auto Continue Rules | **Design only** | AGE-24 Phase 0.5 |

## 3. Phase 1 Evidence → Phase 2 Mapping

| Phase 1 experiment | Verdict | What it proves for AGE-24 |
|---|---|---|
| E1 bootstrap/persistence | PASS | LoopX can host a durable goal state |
| E2 claim conflict | PASS | Exclusive claim prevents simultaneous agents |
| E3 TTL handoff | PASS | Ownership transfers cleanly on TTL expiry |
| E4 multi-process restart | PASS | State is restart-safe |
| E5 refresh-state + history | PASS | Transitions are auditable |

## 4. Gap (needs design, not code)

LoopX provides state, claims, leases, history. It does **not**:
- push to GPT Web (the return path is the existing GPT Relay / Loop A)
- auto-advance phases (the Transition Controller is required)

These two gaps are the core of the AGE-24 Phase 0.5 design and must be
reconfirmed in Phase 3 (integration design, human-gated).

## 5. Boundary

- No production code
- No runtime / Neutral Relay / relay_adapter / auth_verifier change
- No merge, no deploy
- Phase 2 is auto-allowed per Phase Policy (no human gate)

## 6. Final state

Phase 2 complete. The capability matrix is now anchored in real Phase 1
runtime evidence. Next phase per Phase Policy: Phase 3 (integration
architecture design) — **human gate required**.
