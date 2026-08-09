# AgentOps Current Runtime Rules

This is the single current control contract. Older governance/architecture docs are historical when they conflict with this file.

## Roles

- **Linear**: task instructions, acceptance criteria, status, dependencies.
- **GitHub**: code, PRs, reviews, technical evidence, merge state.
- **ChatGPT Web**: architecture, independent review, and decisions during execution.
- **Product Owner**: chooses the task execution mode and gives decisions at manual gates.
- **Relay**: transport only.
- **Builder**: implementation.
- **Controller/Watcher**: keeps the task loop alive across Builder exits and waiting periods.
- **LoopX/runtime state**: durable operational state only.

## Execution mode

Every task starts in one of two modes:

### AUTO

Continue the task loop until the acceptance criteria are satisfied or a real blocker makes execution impossible.

```text
Linear task → Builder → GitHub → GPT Review
CHANGES_REQUESTED / NOT_PASS → Builder fixes → new code HEAD → review again
PASS → continue the task or finish when acceptance criteria are satisfied
```

Do not stop merely because a phase, commit, report, or review round completed.

### MANUAL

The task instruction names the checkpoint/condition where PO input is required.

Run the same Builder ↔ GitHub ↔ GPT loop until that checkpoint is reached, then report the exact state and enter `WAITING_PO_AUTH`.

`WAITING_PO_AUTH` is not Controller termination. Builder may idle/exit; Controller/Watcher stays alive until the PO decision arrives, then execution continues from that decision.

## No risk matrix

There is no LOW/MEDIUM/HIGH runtime risk classifier in the main control flow.

The Builder/GPT may use judgment while executing, but they do not convert that judgment into a separate risk-state machine. If an action is clearly outside the authorized task scope, ambiguous, or impossible to execute safely, surface it as a blocker/decision request instead of inventing a risk tier.

## Acceptance and delivery

For code work, the live remote HEAD must contain the real code change. Docs-only/report-only commits, CI green, or self-declared PASS do not prove a code fix.

Delivery is fail-closed: unconfirmed send/read-back is `DELIVERY_FAILED`; ACK closes only the delivery episode, never the Controller.

The Controller terminates only on accepted completion, closure, or cancellation.
