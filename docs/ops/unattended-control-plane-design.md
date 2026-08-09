# AgentOps Runtime Design

Current runtime semantics live in `docs/governance/CURRENT_RUNTIME_RULES.md`.

This file is retained only as a stable historical path.

The current runtime is a persistent controlled task loop. The Controller/Watcher preserves continuity across Builder exits and waiting periods, follows the task's `AUTO` or `MANUAL` mode, observes GitHub + Linear, and routes review follow-up or PO checkpoints until the task is truly terminal.
