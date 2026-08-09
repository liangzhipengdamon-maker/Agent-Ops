# Linear Guide — AgentOps

> Current task-source contract. Linear is a task/planning source of truth, not an authorization source.

## 1. What Linear owns

Linear stores the active work definition:

- Issue identifier (`AGE-NN`)
- task instructions / implementation intent
- acceptance criteria
- status
- dependencies
- concise progress/evidence links

A local Builder should be able to receive a short instruction such as:

```text
Go to Linear, pick up AGE-X, read the full issue, and execute it.
```

Large copied prompts are not the canonical task definition when the Linear issue already contains the task.

## 2. What Linear does not own

Linear is **not** an authorization source. None of these grant protected-action permission:

- an issue existing
- status = In Progress / Done
- a Linear comment saying “approved”
- a dependency becoming complete
- a due date / timer

Protected actions still follow the canonical governance policy and Product Owner gates.

## 3. Status is projection, not permission

The Builder/Controller may update Linear to reflect factual execution state without treating the status mutation itself as a new authorization event.

Typical projection:

```text
task accepted → In Progress
real blocker  → Blocked
acceptance criteria actually satisfied → Done
```

`Done` means the task's completion criteria are satisfied. It **does not** mean Ready, Merge, Deploy, or any other protected action is authorized.

Do not mark `Done` merely because a report was written, CI is green, or a phase ended.

## 4. Relationship with GitHub and GPT Review

```text
Linear task / acceptance criteria
→ Builder implementation
→ GitHub code + PR + technical evidence
→ GPT Review / decision
→ canonical risk routing
→ Linear status projection
```

GitHub remains the repository/code/review evidence authority. Linear should link to GitHub evidence rather than duplicate full code-review content.

## 5. Issue creation discipline

Do not create a new issue for every review finding, local bug, failed test, or implementation correction when the existing task/PR already owns the work.

Create a new issue only when the work is genuinely a new task with its own lifecycle, scope, or dependency.

## 6. Security / hygiene

Do not store secrets, tokens, private browser-session URLs, or local credentials in Linear.

Authorization may be referenced for traceability, but the Linear record itself never becomes the original authorization source.

## 7. Capability-based access

Linear may be accessed through MCP, GraphQL/API, CLI, or another supported connector. The transport/channel does not change governance semantics.
