# AGE-30 — Runtime Implementation Report

> Implementation of the automation layer defined in AGE-27 (Task
> Intake), AGE-28 (Review Result Intake), and AGE-29 (Risk Judgment
> Policy), combined with the AGE-24 Transition Controller and LoopX
> state management boundaries.

## 1. Architecture Tested

The runtime layer is implemented as a pure-Python package under
`tools/agentops_runtime/`. It composes four pure/transport components:

```
Linear Issue
    ↓
task_intake (discover + notify only)
    ↓
master agent (execution)
    ↓
GitHub PR
    ↓
review_intake (read GitHub review as source of truth)
    ↓
risk_evaluator (AGE-29 matrix)
    ↓
transition_controller (route)
    ↓
  ├─ LOW + PASS      -> AUTO_CONTINUE
  ├─ MEDIUM          -> GPT_DECISION_REQUIRED
  ├─ HIGH            -> WAITING_PO_AUTH (PO final)
  └─ INCOMPLETE      -> WAIT_REVIEW (fail closed)
    ↓
state writeback (task_state.json)
```

## 2. Components

### 2.1 `risk_evaluator.py` (AGE-29)

Pure function `classify_risk(...)` implementing the 10-factor matrix:

- HIGH factors: authorization_change, deployment, merge_action,
  protected_path, irreversible.
- MEDIUM factors: security_boundary, database_schema.
- Fail closed: `unknown_impact=True` or unrecognized explicit level =>
  HIGH.
- Never grants anything; returns `RiskDecision(level, reasons,
  fail_closed)`.

### 2.2 `review_intake.py` (AGE-28)

Reads the authoritative GitHub PR review state (`gh pr view --json
reviewDecision,headRefOid,mergeable`) and parses it:

- `APPROVED` -> decision `PASS` (evidence, not authorization).
- `CHANGES_REQUESTED` -> follow-up.
- HEAD mismatch, merge conflict, unreadable, or review-required ->
  `INCOMPLETE` (fail closed). Never self-approves.

### 2.3 `task_intake.py` (AGE-27)

Filters Linear issues by eligibility (startable state + non-empty
title + authorized repo) and writes `TASK_DISCOVERED` records to an
intake queue. Discover + notify only; never claims or executes.
Duplicate-claim prevention is delegated to LoopX lease (not implemented
here, per design).

### 2.4 `transition_controller.py` (AGE-24 + AGE-29)

Pure routing `route_decision(risk, review)`:

| risk | review | route |
|---|---|---|
| HIGH | any | WAITING_PO_AUTH |
| MEDIUM | any | GPT_DECISION_REQUIRED |
| LOW | PASS | AUTO_CONTINUE |
| LOW | CHANGES_REQUESTED | FOLLOW_UP_REQUIRED |
| LOW | INCOMPLETE/BLOCKED/COMMENTED | WAIT_REVIEW |

Plus `write_state(...)` that appends the outcome to the durable
`task_state.json`. It never grants merge/deploy.

### 2.5 `__main__.py` (CLI)

- `risk-evaluate --flags <flag>...`
- `review-intake <repo> <pr> <head> [--json <file>]`
- `task-intake <repo> <queue-dir> [--issues-json <file>]`
- `transition <risk> <review>`

## 3. State Transitions (validated by tests)

| Input | Outcome | Test |
|---|---|---|
| classify_risk(deployment=True) | HIGH | PASS |
| classify_risk() | LOW | PASS |
| classify_risk(unknown_impact=True) | HIGH (fail closed) | PASS |
| review APPROVED + head match | PASS | PASS |
| review APPROVED + head mismatch | INCOMPLETE (fail closed) | PASS |
| review APPROVED + merge conflict | INCOMPLETE (fail closed) | PASS |
| route(HIGH, PASS) | WAITING_PO_AUTH | PASS |
| route(MEDIUM, PASS) | GPT_DECISION_REQUIRED | PASS |
| route(LOW, PASS) | AUTO_CONTINUE | PASS |
| route(LOW, CHANGES_REQUESTED) | FOLLOW_UP_REQUIRED | PASS |
| route(LOW, INCOMPLETE) | WAIT_REVIEW | PASS |

## 4. Policy Decisions

- **HIGH** risk always routes to `WAITING_PO_AUTH`. PO authorization is
  never bypassed, and the runtime never auto-merges or auto-deploys.
- **MEDIUM** risk routes to `GPT_DECISION_REQUIRED` — GPT Web (the
  independent reviewer) must give a verdict.
- **LOW** risk + `PASS` auto-continues; LOW + `CHANGES_REQUESTED`
  becomes a follow-up; LOW + incomplete evidence waits.
- Fail closed on unknown impact / ambiguous review.

## 5. LoopX / AgentOps Boundary

- This runtime does **not** replace LoopX state management; it writes the
  routing outcome to a local `task_state.json` (the same state that the
  Transition Controller / LoopX syncs). Actual LoopX lease/claim
  integration is out of scope for the runtime modules and remains the
  Master Agent's responsibility per AGE-27.
- AgentOps governance is preserved: GitHub PR review is evidence,
  GPT Web is the independent reviewer, PO authorization is final for
  HIGH risk.

## 6. Failures and Limitations

1. **No GPT Relay push in this layer**: the runtime computes the routing
   decision but does not itself push to GPT Web. The push remains the
   Neutral Relay's job (AGE-19), driven by the Master Agent.
2. **No real LoopX writeback**: the modules write a local `task_state.json`
   as the durable projection; wiring this into `loopx refresh-state` is a
   follow-up (Master Agent integration), not part of these pure modules.
3. **No daemon/scheduler**: per AGE-27 constraint, the CLI is invoked at
   phase boundaries, not a background service.
4. **Linear/GitHub network calls are not implemented in the modules**:
   `task-intake` and `review-intake` accept JSON fixtures for tests; a
   real Linear MCP / GitHub `gh` integration is a thin caller wrapper,
   not part of the pure core.

## 7. Recommendation for Next Phase

- Wire `transition_controller` output into a LoopX `refresh-state` +
  GPT Relay push so the routing decision is both persisted in LoopX and
  delivered to GPT Web automatically (closes AGE-22 delivery gap).
- Add a real Linear MCP / `gh` caller wrapper for the intake modules.
- Validate the end-to-end sandbox flow (mirroring AGE-26) with a real
  Linear issue + GitHub PR.

## 8. Boundary

- No auto-merge, no auto-deploy.
- GPT Web reviewer not replaced.
- PO authorization not bypassed (HIGH -> WAITING_PO_AUTH).
- LoopX and AgentOps boundaries preserved.
- No daemon/scheduler/web service.
- Local Execution Agent role only.
