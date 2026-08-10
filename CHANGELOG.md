# Changelog

All notable public releases of GovernLoop will be documented here.

The project is preparing its first open-source pre-release.

## [Unreleased]

### Added

- public open-source documentation and Quick Start
- Apache License 2.0
- contribution and security policies
- localhost-only first-run ChatGPT reviewer binding wizard
- canonical `governloop_runtime` CLI/runtime facade
- canonical `GOVERNLOOP_*` authority environment and `~/.governloop/` local state

### Changed

- public project identity frozen as **GovernLoop** — “Governed autonomy for coding agents.”
- pre-release AgentOps names moved behind a temporary compatibility layer rather than remaining public API
- GitHub Actions baseline now validates the GovernLoop facade plus the proven pre-v0.1 regression suites

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
- Final Result Auto-Review from delivered `WAITING_REVIEW` to independent review
- exact-current-HEAD review binding
- automatic remediation loop after `CHANGES_REQUESTED` / `NOT_PASS`

### Scope & Action Firewall

- explicit episode-external repository authority
- exact branch and baseline binding
- explicit allowed paths and allowed operations
- local git-origin verification
- clean-worktree contamination checks
- authoritative PR changed-file checks
- fail-closed unreadable-scope behavior
- rejection of traversal, absolute paths, wildcard broadening, protected paths, and disallowed operations
- no implied Ready / Merge / Deploy authority from CI, review, ACK, runtime state, or Builder text

### Onboarding

- first-run reviewer-binding setup on localhost
- exact ChatGPT conversation URL binding
- deterministic CDP Test Connection requiring exactly one matching tab
- no ChatGPT credential collection or storage

### Governance

- canonical runtime rules in `docs/governance/CURRENT_RUNTIME_RULES.md`
- runtime model `AUTO | MANUAL`; historical LOW/MEDIUM/HIGH routing is not part of current control flow
- Linear as current task/status adapter, GitHub as code/evidence source, Product Owner as lifecycle authority

### Known limitations

- repository-first developer workflow; no packaged installer yet
- full external-project onboarding still requires Builder, Linear, and browser-runtime integration
- GitHub CLI is required for live PR evidence
- Neutral Relay and LoopX remain environment-specific integrations
- the first real cross-project pilot remains release-validation work in progress
- a thin pre-v0.1 naming compatibility bridge remains and should be removed in a later breaking cleanup after external migration evidence exists
