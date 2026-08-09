# Agent-Ops

AgentOps is an agent-neutral control plane for governed, long-running software work.

## Current operating model

- **GitHub main** — repository code, governance documents, reviews, and technical evidence.
- **Linear** — task source of truth for task instructions, acceptance criteria, status, and dependencies. Linear is **not** an authorization source.
- **ChatGPT Web** — primary reviewer / architecture / decision layer.
- **Neutral Relay / GPT Relay** — transport only.
- **Local Builder** — implementation and execution.
- **LoopX / runtime state** — durable task continuity, lease, recovery, and handoff.

## Canonical loop

```text
Linear task
→ Builder executes within the authorized task/scope
→ GitHub code/evidence/PR
→ GPT review
→ risk evaluation
   LOW    → auto-continue
   MEDIUM → GPT decision
   HIGH   → WAITING_PO_AUTH
```

`CHANGES_REQUESTED` is a remediation transition, not a task stop. The Builder fixes the current-HEAD findings and produces a new HEAD.

`WAITING_PO_AUTH` is a persistent waiting state, **not controller termination**. The Builder may become idle or exit, but the Controller/Watcher remains alive and continues observing GitHub and Linear.

## Authorization boundary

Review, CI, Linear state, reports, timers, and transport success are evidence only; none grants authorization.

Explicit Product Owner authorization remains required for protected actions such as **Ready, Merge, Deploy, production access, force push / main-history rewrite, and authorization-policy changes**. Ordinary implementation steps inside an already authorized task/scope do not require a new PO authorization for every file edit, test, commit, push, or draft-PR update.

See `docs/governance/AGE-20_GOVERNANCE_BASELINE_V1.md` for the current governance semantics. Older architecture documents are historical when they conflict with that baseline.
