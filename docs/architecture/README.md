# Architecture Documentation

Architecture documents in this directory may include historical designs. They are not automatically the current governance authority.

## Current precedence

For current control semantics, use:

1. `docs/governance/AGE-20_GOVERNANCE_BASELINE_V1.md`
2. `.agent-bridge/AGENT_RUNNER_PROMPT.md`
3. `docs/governance/governance_stop_auto_report.md`
4. `docs/ops/unattended-control-plane-design.md`

When an older architecture document conflicts with those current documents, the current governance baseline wins.

## AGE-3

`age-3-authority-and-mission-authorization-design.md` is now a **Historical / Superseded** design record.

Retained principles:

- Product Owner is the protected-action authorization authority.
- Review/CI/Linear/runtime signals are evidence, not authorization.
- Fail closed on ambiguity/drift.
- Protected actions acting on an existing commit use exact binding required by the current gate.

Superseded runtime assumptions include universal one-action-per-wake suspension, terminal treatment of intermediate waiting/review states, and requiring future final implementation HEADs before ordinary implementation can proceed.
