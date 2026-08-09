# AgentOps Current Runtime Rules

This is the single current control contract. Older governance/architecture docs are historical when they conflict with this file.

## Sources and roles

- **Linear**: task instructions, acceptance criteria, status, dependencies. Not authorization.
- **GitHub**: code, PRs, reviews, technical evidence, merge state.
- **ChatGPT Web**: architecture, independent review, medium-risk decisions.
- **Product Owner**: explicit authorization for protected/high-risk actions.
- **Relay**: transport only.
- **Builder**: implementation.
- **Controller/Watcher**: continuity and Review/Risk/Transition.
- **LoopX/runtime state**: durable operational state only.

## Control loop

```text
Linear task
→ Builder implements
→ GitHub code/evidence
→ GPT Review
   CHANGES_REQUESTED / NOT_PASS → Builder fixes → new code HEAD → review again
   PASS → Risk
      LOW    → AUTO_CONTINUE
      MEDIUM → GPT_DECISION_REQUIRED
      HIGH   → WAITING_PO_AUTH
```

Phase completion is a checkpoint, not termination.

`WAITING_PO_AUTH` is not Controller termination. Builder may idle/exit; Controller/Watcher stays alive, watches GitHub + Linear, and re-routes on meaningful change.

## Authorization

Review, CI, Linear state, reports, timers, transport success, and ACK/read-back are evidence only.

Inside an already authorized task/scope, ordinary edit/test/fix/commit/push/draft-PR-update work continues without fresh PO approval for every step.

Explicit PO authorization remains required for protected/high-risk actions such as Ready, Merge, Deploy/production access, force push/main-history rewrite, authorization-policy/scope changes, and other canonical HIGH actions. Protected actions acting on an existing commit bind the exact live HEAD required by the gate.

## Acceptance and delivery

For code work, the live remote HEAD must contain the real code change. Docs-only/report-only commits, CI green, or self-declared PASS do not prove a code fix.

Delivery is fail-closed: unconfirmed send/read-back is `DELIVERY_FAILED`; no false success timestamp. ACK closes only the delivery episode, never the Controller.

The Controller terminates only on an explicitly terminal task outcome such as accepted completion, closure, or cancellation—not because a phase ended, Builder exited, review requested changes, the task is waiting for PO, or a report was acknowledged.
