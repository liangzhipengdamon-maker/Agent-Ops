# AgentOps Builder Contract

Read and follow `docs/governance/CURRENT_RUNTIME_RULES.md`.

Builder-specific requirements:

- Read the active Linear issue and current GitHub/PR state before acting.
- Continue ordinary implementation inside the active authorized task/scope until review, a real gate, a blocker, or true terminal completion.
- `CHANGES_REQUESTED` / `NOT_PASS` means fix the current-HEAD findings and produce a new code HEAD.
- Do not create a second risk policy; use the canonical runtime risk policy.
- Do not treat Builder exit, phase completion, reports, CI, or ACK as Controller termination.
- Do not claim a code fix from a docs-only/report-only commit.
- Do not infer Ready/Merge/Deploy or other protected-action authorization from evidence.
