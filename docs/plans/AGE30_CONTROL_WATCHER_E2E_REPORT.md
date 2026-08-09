# AGE-30 Control Watcher — Real E2E Validation Report

> Full authoritative record for the AGE-30 main control loop correction:
> WAITING_PO_AUTH is the Control Watcher's START condition, not the
> task's termination condition. Builder STOP != Controller STOP.
>
> Real end-to-end validation A-G. The concise Completion Report sent to
> GPT Web via Neutral Relay references this document by path + URL.

## 1. Task

Correct the AgentOps main control loop so that after entering
WAITING_PO_AUTH the Builder may exit but the AgentOps Controller keeps
running.

Minimal implementation added in PR #31:
- `tools/agentops_runtime/control_watcher.py` — persistent Control
  Watcher loop
- `tools/agentops_runtime/github_poller.py` — real GitHub PR/HEAD/review/
  status polling via `gh` (read-only, fail closed)
- `tools/agentops_runtime/linear_adapter.py` — thin read-only Linear
  adapter via GraphQL (`LINEAR_ACCESS_TOKEN`), never fabricates
- `__main__.py` — `watch` subcommand + `--start-watcher` auto-launch on
  WAITING_PO_AUTH

## 2. Fixed behavior / Result

```
WAITING_PO_AUTH
  -> send concise Completion Report via Neutral Relay (immediate)
  -> launch persistent Control Watcher (detached, survives Builder exit)
  -> every 10 min poll GitHub + Linear (real state)
  -> no change -> continue sleep
  -> change -> Review Intake / Task Intake / Risk Policy / Transition
     Controller (existing modules)
       LOW   -> RESUME (wake execution flow)
       MEDIUM-> request GPT Web decision via Relay
       HIGH  -> stay WAITING_PO_AUTH; notify GPT/PO only on new info
  -> run until true terminal state (PR merged / Linear Done)
```

Guarantees:
- Builder STOP != Controller STOP.
- Notify on change ONLY (never every-10-min spam).
- Single-instance PID guard (no duplicate watchers).
- No auto-merge, no auto-deploy, no PO bypass.
- Risk Policy, PO Authorization, Merge/Deploy rules unchanged.

## 3. Implementation

- `control_watcher.py`:
  - PID + runtime state in `~/.agentops/watcher/<task>.json`
  - `acquire()` single-instance guard (refuses duplicate if PID alive)
  - `_snapshot()` reads real GitHub (`gh pr view`) + real Linear
    (GraphQL) state
  - `_changed(a,b)` state-diff
  - `_handle_change()` re-runs Review Intake / Risk Policy / Transition
    Controller; routes LOW/MEDIUM/HIGH
  - `_should_notify(prev)` notify only when the current PR state differs
    from the PREVIOUS snapshot (prevents both silent changes and spam)
  - `_is_terminal()` exits on PR merged / Linear Done
- `github_poller.py`: `read_pr_state`, `read_pr_head` via `gh`
- `linear_adapter.py`: resolve `AGE-30` by team + identifier via Linear
  GraphQL; returns real `{identifier,title,updated_at,state}` or None

## 4. Live validation evidence (A-G)

Run from the real CLI runtime entry:
```
python -m agentops_runtime transition HIGH PASS \
  --repo liangzhipengdamon-maker/Agent-Ops --pr 31 \
  --task-id AGE-30 --deliverable-path ... --deliverable-url ... \
  --start-watcher --watcher-interval 15 --watcher-state-dir ...
```

### A. Real CLI entry -> HIGH -> WAITING_PO_AUTH
- outcome.route = `WAITING_PO_AUTH`; risk HIGH
- po_notify.status = `DELIVERED` (readback_confirmed=true,
  correlation CPL_647dd338e2da)

### B. Local Builder exits; Controller continues
- Builder CLI returned (exited).
- Watcher pid `89010` runs detached (PPID=1), still alive.

### C. GPT Web auto-received Completion Report (no manual copy)
- Read-back of GPT Web control channel:
  - correlation_id present, HEAD present, PR present,
    deliverable_path present, end_marker present -> AUTO-RECEIVED YES

### D. Controller still alive after Builder exit
- Watcher pid `89010` alive (elapsed > 4 min in E2E; interval default
  600s; E2E used 15s to demonstrate).

### E. Modify GitHub test state
- Added label `age30-watcher-test` to PR #31 -> PR `updatedAt` changed
  from 08:33:31Z to 08:37:17Z (real GitHub state change).

### F. Watcher auto-detects change and enters Transition/Risk flow
- Watcher detected the change (runtime last_github.updated_at ->
  08:37:17Z).
- Routed HIGH -> WAITING_PO_AUTH via existing Transition/Risk path.
- Auto-notified GPT Web (correlation CPL_f78a582b81f7,
  last_notify_at 16:40:40).
- GPT Web confirmed: "Builder STOP -> Watcher 继续运行 -> 检测变化 ->
  自动通知 GPT 这条 HIGH 路径已经真实跑通".
- No notify spam: subsequent idle polls did NOT re-notify.

### G. No manual copy / no restart / no manual relay trigger
- Everything automatic: Builder CLI, watcher spawn, GitHub change,
  watcher detection, notify via relay.

## 5. Requirements verification

| Requirement | Result |
|---|---|
| No new issue / no new architecture (in PR #31) | PASS |
| Thin control-watch/runtime loop | PASS |
| WAITING_PO_AUTH is watcher START, not termination | PASS |
| Builder STOP != Controller STOP | PASS (watcher survives) |
| GitHub: real PR/HEAD/review/status, change-trigger | PASS |
| Linear: real read (thin adapter), not hand-passed JSON | PASS (real AGE-30 read) |
| Relay: immediate Completion Report; notify-on-change only | PASS |
| Watcher survives Builder exit; PID/runtime state; no duplicate | PASS |
| Risk Policy / PO Auth / Merge-Deploy rules unchanged | PASS |
| No auto-merge / auto-deploy / PO bypass | PASS |

## 6. Governance boundaries

- Risk Policy (AGE-29) unchanged.
- PO Authorization rules unchanged.
- Merge / Deploy rules unchanged.
- No auto-merge, no auto-deploy, no PO bypass.
- Local Execution Agent = Builder; GPT Web = Independent Reviewer.
- Neutral Relay reused (AGE-19), no new architecture.

## 7. PR / branch / HEAD / CI

- Branch: `feat/age-30-waiting-po-notify`
- HEAD: `0f4a495a705fbd9204875819d29f0b7ee9b590b8`
- PR #31 (Draft): https://github.com/liangzhipengdamon-maker/Agent-Ops/pull/31
- CI: PASS on this HEAD (test job)
- Tests: 50 runtime tests (incl. watcher: change-detect, PID guard,
  routing, terminal, notify-baseline) + 71 neutral relay + relay adapter

## 8. Deliverable

This file: `docs/plans/AGE30_CONTROL_WATCHER_E2E_REPORT.md`
GitHub URL:
https://github.com/liangzhipengdamon-maker/Agent-Ops/blob/feat/age-30-waiting-po-notify/docs/plans/AGE30_CONTROL_WATCHER_E2E_REPORT.md

## 9. Current state

- Control Watcher for AGE-30 is **still running** (pid 89010) and was NOT
  stopped after the report.
- Governance state: WAITING_PO_AUTH.
- Waiting: PO merge authorization for PR #31 HEAD
  `0f4a495a705fbd9204875819d29f0b7ee9b590b8`.

---

## Addendum — Watcher → Builder wake loop closure (f1144b2, b3a6f83)

GPT's determination: `GPT → GitHub Review → Watcher PASS; Watcher → Review Intake → Builder 执行修复 FAIL`.

Closed the blocker:
- `_emit_builder_wake()`: on a detected GitHub change, the watcher writes a
  `BUILDER_WAKE` event (repo/pr/head/review_decision/route/action =
  execute_follow_up) that the Builder consumes via `agentops_runtime wake`.
- Emitted on AUTO_CONTINUE, GPT_DECISION_REQUIRED, and ANY HIGH change
  (before the blocking relay notify, so the Builder can act immediately).
- Live verification: triggered a NEW GitHub comment on PR #31 ->
  watcher detected (updated_at -> 10:03:27Z) -> emitted wake_AGE-30.json
  (head b3a6f83, action execute_follow_up) -> Builder consumed it via CLI.
- Builder then executes the fix, commits, pushes -> new HEAD -> watcher
  re-evaluates. The P0 fixes (dynamic risk, delivery fail-closed, wake)
  are committed at HEAD b3a6f83.
