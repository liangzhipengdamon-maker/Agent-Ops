# AgentOps Builder Contract

Read and follow `docs/governance/CURRENT_RUNTIME_RULES.md`.

Builder-specific requirements:

- Read the active Linear issue and current GitHub/PR state before acting.
- Read the task execution mode: `AUTO` or `MANUAL`.
- `AUTO`: keep executing and reviewing until acceptance criteria are satisfied or a real blocker prevents progress.
- `MANUAL`: keep executing until the task's named PO checkpoint/condition, then report exact state and wait for the PO decision.
- `CHANGES_REQUESTED` / `NOT_PASS`: fix the current-HEAD findings and produce a new code HEAD.
- Do not create or use a LOW/MEDIUM/HIGH risk state machine for normal routing.
- Do not treat Builder exit, phase completion, reports, CI, or ACK as Controller termination.
- Do not claim a code fix from a docs-only/report-only commit.
- If work is outside the authorized task scope, ambiguous, or genuinely blocked, surface it explicitly instead of inventing a risk tier.
