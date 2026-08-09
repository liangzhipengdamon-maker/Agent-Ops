# AgentOps Runtime Design

Current runtime semantics live in `docs/governance/CURRENT_RUNTIME_RULES.md`.

This file is retained only as a stable historical path.

The current runtime is a persistent controlled task loop, not a universal one-action-per-wake system. Builder may stop at real gates; Controller/Watcher preserves continuity and re-routes Review/Risk/Transition until the task is truly terminal.
