# Changelog

All notable public releases of AgentOps will be documented here.

The project is currently preparing its first open-source pre-release.

## [Unreleased]

### Added

- public open-source documentation and quick start
- Apache License 2.0
- contribution and security policies
- v0.1.0 release-readiness checklist

## [0.1.0] - planned

### Core control loop

- thin AUTO / MANUAL runtime decision loop
- persistent Controller/Watcher across Builder exits and waiting periods
- MANUAL named checkpoint semantics with durable `WAITING_PO_AUTH`
- accepted-completion evidence bound to exact PR + HEAD
- Product Owner decisions bound to exact PR + HEAD

### Independent review and delivery

- status-report delivery through a Neutral Relay boundary
- strict correlated ACK handling
- Final Result Auto-Review path from delivered `WAITING_REVIEW` report to independent review
- exact-current-HEAD review binding
- automatic remediation loop after `CHANGES_REQUESTED` / `NOT_PASS`

### Scope & Action Firewall

- explicit out-of-episode repository authority
- exact branch and baseline binding
- explicit allowed paths and allowed operations
- local git-origin verification
- clean-worktree contamination checks
- authoritative PR changed-file checks
- fail-closed behavior for unreadable scope evidence
- rejection of path traversal, absolute paths, wildcard broadening, protected paths, and disallowed operations
- no implied Ready / Merge / Deploy authority from CI, review, ACK, runtime state, or Builder text

### Governance

- canonical runtime rules consolidated in `docs/governance/CURRENT_RUNTIME_RULES.md`
- runtime model simplified to `AUTO | MANUAL`; historical LOW/MEDIUM/HIGH risk routing is not part of the current control flow
- Linear retained as task/status source, GitHub as code/evidence source, and Product Owner decisions as lifecycle authority

### Known limitations

- repository-first developer workflow; no packaged installer yet
- Linear is the currently implemented task adapter
- GitHub CLI is required for live PR evidence
- Neutral Relay and LoopX integrations require environment-specific setup
- external-project onboarding is not yet a one-command experience
- first cross-project real-world pilot is still part of v0.1 validation
