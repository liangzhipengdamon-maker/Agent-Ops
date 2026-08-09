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

Before execution starts, every task must specify exactly one mode: `AUTO` or `MANUAL`.

The mode controls **when the loop pauses**. It does not expand the task scope or acceptance criteria. If the mode is missing or ambiguous, surface a decision request instead of inventing a default.

### AUTO

Keep the task loop running through the in-scope steps needed to satisfy the acceptance criteria.

```text
Linear task → Builder → GitHub → GPT Review
CHANGES_REQUESTED / NOT_PASS → Builder fixes → new code HEAD → review again
PASS → continue in scope or finish when acceptance criteria are satisfied
```

Do not stop merely because a phase, commit, push, PR update, report, or review round completed. AUTO may continue through lifecycle steps that are already inside the task scope; it must not invent unrelated work.

### MANUAL

The task instruction must name the checkpoint or condition where PO input is required.

Run the same Builder ↔ GitHub ↔ GPT loop until that checkpoint is reached, then report the exact state and enter `WAITING_PO_AUTH`.

`WAITING_PO_AUTH` is not Controller termination. Builder may idle/exit; Controller/Watcher stays alive until the PO decision arrives, then execution continues from that decision.

## No risk matrix

There is no LOW/MEDIUM/HIGH runtime risk classifier in the main control flow.

Builder and GPT use judgment directly. If work is outside the task scope, ambiguous, or cannot be executed safely, surface a blocker or decision request instead of creating a risk tier or a new gate system.

## Acceptance and delivery

For code work, the live remote HEAD must contain the real code change. Docs-only/report-only commits, CI green, or self-declared PASS do not prove a code fix.

Delivery is fail-closed: unconfirmed send/read-back is `DELIVERY_FAILED`; ACK closes only the delivery episode, never the Controller.

The Controller terminates only on accepted completion, closure, or cancellation.
