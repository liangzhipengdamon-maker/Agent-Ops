# AGE-20 Governance Baseline — Current Control Semantics

> Canonical governance semantics for current AgentOps development.
>
> This document defines control behavior and precedence. It does **not** by itself prove that every runtime path already implements the behavior; implementation must still be verified on the actual production entrypoint.

## 1. Precedence

When AgentOps governance documents conflict, use this order:

1. explicit current Product Owner instruction for authorization decisions;
2. this governance baseline for control semantics;
3. current task acceptance criteria in Linear for task behavior/scope;
4. current GitHub main code/docs/review evidence for repository facts;
5. historical design documents only as background.

Legacy AGE-3 / early unattended-control-plane rules such as universal one-action-per-wake, `WAITING_PO_AUTH` as terminal, or Linear as status-only are superseded where they conflict with this baseline.

## 2. Roles and authorities

- **Product Owner** — authorization authority for protected actions and risk escalation that requires human approval.
- **ChatGPT Web** — primary architecture/review/decision layer; review is evidence, not authorization.
- **Neutral Relay / GPT Relay** — transport only.
- **Local Builder** — implements and verifies changes.
- **Controller / Watcher** — preserves continuity, observes state changes, routes Review/Risk/Transition, and keeps the task alive across Builder exits.
- **LoopX / runtime state** — durable operational state, recovery, lease/handoff; not an authorization source.
- **GitHub main** — repository code/governance/review evidence authority.
- **Linear** — task source of truth for instructions, acceptance criteria, status, and dependencies; not an authorization source.

## 3. Continuous task loop

```text
Linear task
→ Builder executes within the active authorized task/scope
→ GitHub code/evidence/PR
→ GPT Review
→ canonical Risk Evaluation
   LOW    → AUTO_CONTINUE
   MEDIUM → GPT_DECISION_REQUIRED
   HIGH   → WAITING_PO_AUTH
→ state change
→ repeat until truly terminal
```

**Phase completion is a checkpoint, not termination.**

Ordinary implementation may span multiple edits, tests, commits, pushes, review rounds, and phase boundaries without obtaining a fresh PO authorization at every step, provided execution remains within the active authorized task/scope and no protected gate is crossed.

## 4. Review semantics

Review outcomes are evidence:

- `CHANGES_REQUESTED` / `NOT_PASS` → remediation transition; Builder consumes exact current-HEAD findings and fixes them.
- `PASS` → review satisfied; then run risk evaluation. PASS does not automatically mean wait for PO.
- `BLOCKED` / `NEEDS_OWNER_DECISION` → escalate conservatively through risk/decision routing.
- stale-HEAD review → reject; never apply stale remediation or stale PASS to a new HEAD.

When native GitHub `REQUEST_CHANGES` is unavailable, a formal Review `COMMENT` may carry a machine-readable verdict and remediation bound to the exact current HEAD. Its body must be consumable by the runtime/Builder; merely detecting that “a review changed” is insufficient.

## 5. Canonical risk routing

The runtime must use one canonical risk policy implementation. No component may introduce a second ad-hoc risk classifier.

```text
LOW    → AUTO_CONTINUE
MEDIUM → GPT_DECISION_REQUIRED
HIGH   → WAITING_PO_AUTH
```

Unknown, ambiguous, missing, or unmapped impact fails closed according to the canonical policy.

## 6. WAITING_PO_AUTH is non-terminal

`WAITING_PO_AUTH` means:

- Builder may idle or exit;
- Controller/Watcher **must remain alive**;
- GPT/PO must receive exact state evidence through the reporting path;
- Controller continues observing GitHub and Linear;
- meaningful changes trigger Review/Risk/Transition again.

A report ACK/read-back closes only that delivery episode. It does not terminate the Controller.

The same principle applies to `CHANGES_REQUESTED`, `BLOCKED`, and `NEEDS_OWNER_DECISION`: they can pause an execution path, but they are not automatic controller-death states.

## 7. Authorization boundary

The following are **never authorization by themselves**:

- review PASS / comment
- CI green
- Linear status or Done
- timer/polling event
- push/transport success
- Builder completion report
- status/completion report ACK/read-back
- matching SHA without explicit authority provenance

An active implementation authorization binds the task/base/scope and allows ordinary execution inside that boundary. It must not require the final future HEAD before implementation creates that HEAD.

Explicit Product Owner authorization remains required for protected actions including:

- Ready for Review
- Merge
- Deploy / production access
- force push / main-history rewrite
- authorization-policy or authorization-scope changes
- any other action classified HIGH by the canonical policy

For protected actions that act on an existing commit, authorization/verifier logic must bind the exact live 40-character HEAD required by that gate.

## 8. GitHub / Linear separation

### GitHub

Owns repository facts: code, governance docs, PRs, reviews, technical evidence, and merge state.

### Linear

Owns task facts: task instructions, acceptance criteria, status, dependencies, and concise evidence links.

Linear status is projection, not authority. The Builder/Controller may update factual status as work progresses. `Done` means acceptance criteria are actually satisfied; it does not grant Ready/Merge/Deploy.

## 9. Completion evidence rules

Self-report is never enough.

For code tasks, completion requires the live remote HEAD to contain the actual implementation change. A docs-only report commit cannot be used to claim a runtime/code defect was fixed.

Acceptance must be based on externally observable production-path behavior and relevant tests/E2E evidence, not on internal logs that merely print `PASS`.

## 10. Reporting / delivery rules

- Reports are evidence only.
- Delivery must be fail-closed: unconfirmed send/read-back must produce explicit delivery failure, not a success timestamp.
- Retries must be bounded and duplicate-safe.
- Report generation must not become the task itself.
- Concise high-information reports are preferred; full detail may remain in GitHub when appropriate.

## 11. Controller termination

The Controller terminates only when the task/mission reaches an explicitly terminal outcome under current policy (for example explicit completion/closure/cancellation), not because:

- a phase ended;
- Builder exited;
- review asked for changes;
- the task is waiting for PO;
- a report was acknowledged.

## 12. Non-goals

This baseline does not authorize automatic Merge/Deploy, remove fail-closed behavior, or turn review evidence into permission. It only removes contradictory legacy stop/gating semantics that prevented the intended controlled long-running loop.
