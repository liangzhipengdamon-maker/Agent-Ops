# AGE-21 Pilot Entry — Long-Task Automation Workflow Validation

> Pilot entry for AGE-21.
> This is a pilot-validation artifact, not autonomous execution.

## Purpose

AGE-21 is a pilot to validate that AgentOps can run a long-running task
through the full governance loop end-to-end:

```
Task Intake → Planning → Execution → Self Check
→ Independent Review → PO Authorization
```

This document is the pilot entry log. It records:

- the scope that was executed (minimal)
- the boundaries that were enforced
- the governance flow exercised
- the review handoff performed via Neutral Relay

## Pilot scope executed (minimal, docs-only)

Single artifact:

- `docs/pilots/AGE-21_PILOT_ENTRY.md` — this file

Scope: documentation only. No production code, no runtime change, no
Neutral Relay / auth_verifier / relay_adapter / CI / config changes,
no autonomous execution capability, no Runner, no Executor, no daemon,
no scheduler.

## Boundaries enforced (from AGE-21)

The Builder (this agent run) **did not** perform:

- automatic merge
- automatic deploy
- governance rule changes
- authorization system changes
- Neutral Relay changes without authorization
- starting of other AGE tasks automatically
- any scope expansion beyond this pilot artifact

## Governance flow exercised

| Step | Evidence |
|---|---|
| Task Intake | Read `AGE-21` from Linear (project `AgentOps`, state `Backlog`) |
| Plan | This `docs/pilots/AGE-21_PILOT_ENTRY.md` defines the minimal pilot scope |
| Implementation | One docs-only file added; no production code change |
| CI | GitHub Actions `test` job on the exact HEAD; PASS required before review |
| Independent Review | Sent via Neutral Relay through the isolated AgentOps runtime (CDP 9233, profile `~/.agentops/chrome-profile`); bound to the exact reviewed HEAD |
| PO Authorization | WAITING_PO_AUTH — no merge, no deploy |

## Runtime isolation (inherited from AGE-19)

- AgentOps Neutral Relay runs only on its dedicated CDP port `9233`.
- LearnMind's CDP `9223` was untouched.
- Runtime guard verifies both the CDP port and the on-disk `AGENTOPS_MARKER`
  file (`AgentOps-9233`); mismatch → `WRONG_BROWSER_RUNTIME` fail closed.
- Conversation identity binding: exact UUID match, zero/one/multi → fail closed.

## Self-check criteria (per AGE-21 success criteria)

| Criterion | Status |
|---|---|
| Long-running task survives interruptions | Deferred (this pilot is single-shot; long-running survives via git/Linear only) |
| Agent state remains recoverable | Pass (working tree recoverable via git) |
| Review handoff works | Pass (sent via Neutral Relay on isolated 9233 runtime) |
| STOP_AND_WAIT works | Pass (Builder stopped at WAITING_PO_AUTH, no merge, no deploy) |
| No unauthorized mutation occurs | Pass (one docs-only file added; PR remains Draft) |

## Final state

`WAITING_PO_AUTH` — awaiting PO merge authorization on the exact reviewed HEAD.