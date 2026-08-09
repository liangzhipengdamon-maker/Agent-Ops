# AGE-3 Authority & Mission Authorization Design — Historical / Superseded

> **Status: Historical design record.**
>
> The original Revision 4 design is preserved in Git history. It is no longer a controlling runtime/governance specification where it conflicts with `docs/governance/AGE-20_GOVERNANCE_BASELINE_V1.md`.

## Why this document was superseded

The early AGE-3 design intentionally maximized fail-closed isolation, but later runtime work showed that several assumptions were too restrictive or no longer matched the production control loop, especially:

- universal **one-action-per-wake** suspension;
- treating many intermediate states as stop/terminal states;
- requiring authorization structures that implied knowledge of a future final HEAD before implementation created it;
- an Outer Runner/TAP model that was never the actual production entrypoint;
- treating long-running execution as repeated isolated wakes instead of a persistent controlled task loop.

Those semantics must not be used to override the current continuous-loop governance baseline.

## Principles retained from AGE-3

The following principles remain valid and are carried forward into the current baseline:

1. **Product Owner authority** — protected actions derive permission only from explicit PO authorization.
2. **Evidence ≠ authorization** — Linear, CI, reviews, runtime state, timers, and transport success do not generate permission.
3. **Fail closed** — ambiguous, missing, conflicting, stale, or unverifiable authorization/risk state does not become implicit approval.
4. **No self-authorization** — Builder/Reviewer/runtime cannot grant their own protected-action permission.
5. **Exact binding for protected actions** — when Ready/Merge/Deploy or another protected action acts on an existing commit, the gate must bind the exact live HEAD required by policy.
6. **Revocation / scope discipline** — active authorization must remain bounded to the intended repository/task/scope and may be revoked.

## Principles explicitly retired as controlling rules

The following old AGE-3 ideas are **non-controlling** unless a future canonical policy explicitly reintroduces them:

- “execute exactly one action and immediately suspend” as a universal runtime rule;
- mandatory stop after every DENY/checkpoint/review round;
- requiring a not-yet-created final implementation HEAD as a prerequisite for ordinary implementation;
- requiring a separate cryptographic TAP/Outer Runner deployment before the current local controlled loop can operate;
- treating every workflow transition as a new PO authorization event.

## Current authority

For current behavior use:

- `docs/governance/AGE-20_GOVERNANCE_BASELINE_V1.md`
- `.agent-bridge/AGENT_RUNNER_PROMPT.md`
- `docs/governance/governance_stop_auto_report.md`
- `docs/ops/unattended-control-plane-design.md`

If this historical file conflicts with any of those current documents, **this file loses precedence**.
