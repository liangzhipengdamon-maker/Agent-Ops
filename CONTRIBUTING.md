# Contributing to GovernLoop

Thanks for helping improve GovernLoop.

GovernLoop is a governance/control-plane project, so small changes to authorization, state transitions, transport, or scope handling can have outsized effects. Contributions are welcome, but control semantics must remain explicit and testable.

## Start here

1. Read [`README.md`](README.md).
2. Read [`docs/governance/CURRENT_RUNTIME_RULES.md`](docs/governance/CURRENT_RUNTIME_RULES.md).
3. For security-sensitive changes, read [`SECURITY.md`](SECURITY.md).

Older architecture/governance documents may be useful historical evidence, but current runtime rules win when they conflict.

## Development principles

Please preserve these invariants unless a proposal explicitly changes the governance contract:

- review evidence is not authorization
- runtime/relay/state storage cannot create authority
- exact repository / branch / baseline / PR / HEAD binding is preferred over inference
- missing or unverifiable control evidence fails closed
- `AUTO` and `MANUAL` are the only current execution modes
- `WAITING_PO_AUTH` is a durable waiting state, not Controller termination
- no LOW/MEDIUM/HIGH risk classifier in the current control flow
- avoid duplicate runtimes, schedulers, state kernels, or agent-specific orchestration layers
- Builder integrations should remain agent-neutral where practical

## Recommended workflow

1. Open or reference an issue describing the problem and acceptance criteria.
2. Create a focused branch from current `main`.
3. Keep the change within stated repository/path/operation scope.
4. Add deterministic tests for positive behavior and relevant fail-closed negatives.
5. Run focused tests, then the full baseline.
6. Open a pull request with problem statement, scope/non-scope, changed files, test evidence, security/governance impact, and known limitations.
7. Review the actual current PR HEAD.

Do not treat CI green, a bot ACK, or a self-authored PASS as permission to merge.

## Tests

Canonical v0.1 facade tests:

```bash
PYTHONPATH=tools python -m unittest discover -s tools/governloop_runtime/tests
```

The CI baseline also runs the pre-v0.1 runtime regression suite and relay suites while the naming compatibility layer remains in place. Consult `.github/workflows/ci.yml` for the authoritative commands.

## Pull request size

Prefer deletion-first, narrow changes. A control-plane fix is easier to review when it modifies an existing boundary instead of adding a parallel abstraction.

If a change genuinely needs a new layer, explain why the existing Controller/Watcher, Builder handoff, Neutral Relay, or LoopX boundary cannot carry it.

## Security-sensitive contributions

Changes touching authorization inputs, repo/branch/baseline/HEAD binding, paths/operations, lifecycle decisions, review identity, relay correlation, worktree contamination, or cross-project isolation should include explicit negative tests.

For suspected vulnerabilities, do **not** open a public exploit report. Follow [`SECURITY.md`](SECURITY.md).

## Naming

New public code and documentation should use the canonical v0.1 names: `GovernLoop`, `governloop_runtime`, `GOVERNLOOP_*`, and `~/.governloop/`. Pre-v0.1 AgentOps names are compatibility/history only. See [`docs/REBRAND_MIGRATION.md`](docs/REBRAND_MIGRATION.md).

## Documentation

When changing current behavior, update the canonical runtime rules or relevant public guide in the same PR. Historical reports should remain clearly historical rather than silently becoming new authority.

## License

By contributing, you agree that your contributions will be licensed under the repository's [Apache License 2.0](LICENSE).
