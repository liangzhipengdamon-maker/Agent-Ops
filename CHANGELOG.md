# Changelog

All notable public releases of GovernLoop are documented here.

The project is preparing its first open-source pre-release.

## [Unreleased]

### Added

- public open-source documentation, Quick Start, contribution, security, and community files
- Apache License 2.0
- canonical GovernLoop public identity and migration guidance from the pre-v0.1 AgentOps name
- installable repository-checkout package metadata and `governloop` console entry point
- localhost-only ChatGPT reviewer binding wizard
- read-only guided `governloop doctor` readiness command
- external signed positive-authority verification through an OS-protected operator channel
- exact-bound external signed completion verification
- canonical exact-bound independent review envelope
- MANUAL lifecycle firewall and decide-first Watcher behavior

### Changed

- public project identity is **GovernLoop** — “Governed autonomy for coding agents.”
- pre-release AgentOps names remain only behind a temporary compatibility layer
- GitHub Actions now smoke-tests `python -m pip install .`, installed `governloop --help`, canonical runtime tests, legacy regression tests, and relay suites
- cold-start onboarding is guided by one dependency-ordered next action instead of requiring source-code archaeology

## [0.1.0] - planned

### Core control loop

- AUTO / MANUAL runtime decision loop
- persistent Controller/Watcher across Builder exits and waiting periods
- MANUAL named checkpoints with durable `WAITING_PO_AUTH`
- exact repository / branch / baseline / PR / HEAD binding
- Product Owner lifecycle actions remain separate from implementation/review evidence

### Independent review and delivery

- status-report delivery through a Neutral Relay boundary
- strict correlated ACK handling
- Final Result Auto-Review from delivered `WAITING_REVIEW` to independent review
- exact-current-HEAD review request binding
- full review envelope binding for request ID, repository, PR, and HEAD
- automatic remediation loop after `CHANGES_REQUESTED` / `NOT_PASS`
- trusted reviewer authority comes only from verified external signed authority

### Scope & Action Firewall

- external signed positive authority binds exact repository, authorized branch, baseline SHA, allowed paths, allowed non-lifecycle operations, and trusted reviewers
- local git-origin and branch verification
- exact signed-baseline ancestry verification
- clean-worktree contamination checks
- authoritative PR changed-file checks
- fail-closed unreadable-scope behavior
- rejection of traversal, absolute paths, wildcard broadening, protected paths, and disallowed operations
- raw env/profile/repository state cannot create missing positive authority
- no implied Ready / Merge / Deploy authority from CI, review, ACK, runtime state, or Builder text

### Completion and lifecycle safety

- accepted COMPLETE requires exact repo / PR / HEAD-bound external signed completion evidence
- legacy Builder-written completion bridge evidence is non-authoritative
- active MANUAL lifecycle violations are checked before terminal handling
- exact-bound external signed Product Owner evidence is required for lifecycle exceptions
- missing gate files do not turn unauthorized CLOSED/MERGED state into a normal terminal result

### Onboarding

- repository-checkout installation with `python -m pip install -e .`
- installed `governloop` console entry point
- first-run reviewer-binding setup on localhost
- exact ChatGPT conversation URL binding
- deterministic CDP Test Connection requiring exactly one matching tab
- no ChatGPT credential collection or storage
- guided `governloop doctor` readiness matrix with exactly one top-level next action
- concise fail-closed diagnostics outside a Git worktree
- clean-room Local Agent cold-start validation demonstrated `clone/install -> doctor -> one external action -> safe stop`

### Governance

- canonical runtime rules in `docs/governance/CURRENT_RUNTIME_RULES.md`
- runtime model is `AUTO | MANUAL`; historical LOW/MEDIUM/HIGH routing is not part of current control flow
- Linear is the current task/status adapter
- GitHub remains the source of truth for code, PR state, CI, and exact review HEAD
- external operator/Product Owner authority is intentionally separate from Builder/runtime evidence

### Known limitations

- the package is pre-release and is **not published on PyPI**; current installation is from a repository checkout
- external signed authority provisioning remains an operator/control-plane responsibility; the Builder/runtime cannot mint its own authority
- Linear is the currently implemented task adapter
- GitHub CLI is required for live PR evidence
- reviewer/browser, Neutral Relay, and LoopX integrations remain environment-specific
- a full real cross-project pilot is useful follow-up evidence but is not claimed complete here
- a thin pre-v0.1 naming compatibility bridge remains and should be removed only through a later explicit breaking-change plan
