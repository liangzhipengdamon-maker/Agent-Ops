# Linear Contract — AgentOps

Linear is the task source of truth for issue instructions, acceptance criteria, status, and dependencies.

The task should record its execution mode (`AUTO` or `MANUAL`). A `MANUAL` task must also name the PO checkpoint/condition.

Linear status, comments, timers, or dependency changes do not choose an execution mode, expand task scope, or stand in for a PO decision at a manual gate.

The Builder should read the active Linear issue directly instead of relying on large copied prompts. Update Linear to reflect factual task state; do not mark `Done` until acceptance criteria are actually satisfied.

Do not create a new issue for a review finding or local fix already owned by the current task/PR.

Current control semantics: `docs/governance/CURRENT_RUNTIME_RULES.md`.
