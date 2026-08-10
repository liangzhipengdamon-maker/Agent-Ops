# Contributing to AgentOps

Thanks for helping improve AgentOps.

AgentOps is a governance/control-plane project, so small changes to authorization, state transitions, transport, or scope handling can have outsized effects. Contributions are welcome, but control semantics must remain explicit and testable.

## Start here

1. Read [`README.md`](README.md).
2. Read the canonical runtime contract: [`docs/governance/CURRENT_RUNTIME_RULES.md`](docs/governance/CURRENT_RUNTIME_RULES.md).
3. For security-sensitive changes, read [`SECURITY.md`](SECURITY.md).

Older architecture/governance documents may be useful historical evidence, but the current runtime rules win when they conflict.

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
2. Create a focused branch from the current `main`.
3. Keep the change within the stated repository/path/operation scope.
4. Add deterministic tests for both the positive path and relevant fail-closed negatives.
5. Run the relevant tests locally.
6. Open a pull request with:
   - problem statement
   - scope and non-scope
   - changed files
   - test evidence
   - security/governance impact
   - known limitations
7. Review should be performed against the actual current PR HEAD.

Do not treat CI green, a bot ACK, or a self-authored PASS as permission to merge.

## Tests

The project currently uses Python `unittest`-style suites plus repository scripts.

The GitHub Actions baseline exercises the runtime and relay suites. When changing a narrow subsystem, run its focused tests first, then the full baseline before requesting final review.

Examples from the current tree:

```bash
PYTHONPATH=tools python -m unittest discover -s tools/agentops_runtime/tests
```

Consult `.github/workflows/` for the current CI commands if the baseline changes.

## Pull request size

Prefer deletion-first, narrow changes. A control-plane fix is easier to review when it modifies one existing boundary instead of adding a parallel abstraction.

If a change genuinely needs a new layer, explain why the existing Controller/Watcher, Builder handoff, Neutral Relay, or LoopX boundary cannot carry it.

## Security-sensitive contributions

Changes touching any of these areas should include explicit negative tests:

- authorization inputs
- repository / branch / baseline / HEAD binding
- allowed paths or operations
- Ready / Merge / Deploy decisions
- review identity and exact-HEAD binding
- relay delivery / ACK correlation
- worktree contamination detection
- cross-project isolation

For suspected vulnerabilities, do **not** open a public exploit report. Follow [`SECURITY.md`](SECURITY.md).

## Documentation

When changing current behavior, update the canonical runtime rules or the relevant public guide in the same PR.

Historical reports should remain clearly labeled as historical/validation evidence rather than silently becoming new authority.

## License

By contributing, you agree that your contributions will be licensed under the repository's [Apache License 2.0](LICENSE).
