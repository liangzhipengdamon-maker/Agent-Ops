# Linear Contract — AgentOps

Linear is the task source of truth for issue instructions, acceptance criteria, status, and dependencies.

Linear is **not** an authorization source. `Done`, comments, timers, or dependency changes never grant Ready/Merge/Deploy or other protected actions.

The Builder should read the active Linear issue directly instead of relying on large copied prompts. Update Linear to reflect factual task state; do not mark `Done` until acceptance criteria are actually satisfied.

Do not create a new issue for a review finding or local fix already owned by the current task/PR.

Current control semantics: `docs/governance/CURRENT_RUNTIME_RULES.md`.
