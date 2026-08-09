# AgentOps Builder Contract

Read and follow `docs/governance/CURRENT_RUNTIME_RULES.md`.

Builder-specific requirements:

- Read the active Linear issue and current GitHub/PR state before acting.
- Read the task execution mode: `AUTO` or `MANUAL`. If it is missing or ambiguous, request a decision; do not choose a default.
- `AUTO`: keep executing and reviewing through in-scope lifecycle steps until acceptance criteria are satisfied or a real blocker prevents progress.
- `MANUAL`: keep executing until the task's named PO checkpoint/condition, then report exact state and wait for the PO decision.
- `CHANGES_REQUESTED` / `NOT_PASS`: fix the current-HEAD findings and produce a new code HEAD.
- Do not create or use a LOW/MEDIUM/HIGH risk state machine or a separate per-action gate system for normal routing.
- Execution mode never expands task scope. Out-of-scope, ambiguous, or genuinely unsafe work must be surfaced explicitly.
- Do not treat Builder exit, phase completion, reports, CI, or ACK as Controller termination.
- Do not claim a code fix from a docs-only/report-only commit.
