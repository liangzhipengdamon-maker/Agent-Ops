# GovernLoop

**Governed autonomy for coding agents.**

GovernLoop is an agent-neutral control plane that keeps coding-agent work moving through implementation, pull requests, independent review, remediation, and explicit lifecycle gates without allowing runtime state, review text, or Builder output to silently expand authority.

> Project status: **v0.1.0 pre-release**. The core AUTO/MANUAL loop, exact-HEAD review path, deterministic Scope & Action Firewall, and first-run ChatGPT reviewer binding are implemented and tested. Packaging and external onboarding are still early-stage.

GovernLoop is **not** an agent observability SDK and it is not another coding agent. It governs the tools you already use.

## Why GovernLoop

Coding agents can implement changes quickly. Long-running autonomous work creates a different problem: **which exact repository, branch, baseline, paths, and operations are authorized—and what happens after the Builder exits or a reviewer asks for changes?**

GovernLoop separates those responsibilities:

- **Builder** implements changes.
- **GitHub** is the source of truth for code, PR state, CI, and exact review HEAD.
- **Linear** currently supplies task instructions, acceptance criteria, mode, and status.
- **Independent reviewer** evaluates the actual current PR HEAD.
- **Controller/Watcher** keeps the loop alive across Builder exits and waiting periods.
- **Neutral Relay** transports review/status messages but has no authority.
- **LoopX/runtime state** stores operational state but has no authorization authority.
- **Product Owner** retains decisions at MANUAL lifecycle gates.

The canonical control contract is [`docs/governance/CURRENT_RUNTIME_RULES.md`](docs/governance/CURRENT_RUNTIME_RULES.md).

## Core workflow

```text
Linear task
    |
    v
Controller / Watcher
    |
    v
 Builder  --------->  GitHub PR  --------->  Independent review
    ^                                          |
    |                                          |
    +------ CHANGES_REQUESTED / NOT_PASS <-----+
                                               |
                                               v
                                             PASS
                                               |
                      +------------------------+-----------------------+
                      |                                                |
                    AUTO                                             MANUAL
             continue in scope                         named checkpoint reached
             or accepted completion                    -> WAITING_PO_AUTH
```

A review `PASS` is technical evidence. It is **not** implicit permission to broaden scope or perform Ready / Merge / Deploy.

## Safety model

The v0.1 runtime includes a deterministic Scope & Action Firewall at the Builder wake boundary. Positive authority is explicit and episode-external:

- exact repository
- exact authorized branch
- exact baseline SHA
- allowed path prefixes
- allowed operations

The firewall also checks local git origin, current worktree branch, uncommitted contamination, and the authoritative PR changed-file set. Missing or unverifiable authority fails closed and produces no executable Builder wake.

Rejected conditions include wrong repository/branch/baseline, path traversal or wildcard broadening, committed or uncommitted changes outside allowed paths, disallowed operations, unreadable remote/local evidence, task switching, and implied lifecycle authority from review, CI, ACK, runtime state, or Builder instructions.

See [`SECURITY.md`](SECURITY.md) for the trust and threat model.

## Execution modes

GovernLoop intentionally has only two runtime modes.

### AUTO

The controlled Builder → GitHub → independent-review loop continues through in-scope remediation and continuation until accepted completion or a real blocker.

### MANUAL

The same loop runs until a **named checkpoint** is reached. The Controller then enters `WAITING_PO_AUTH` and stays alive while awaiting a Product Owner decision.

There is no LOW / MEDIUM / HIGH risk classifier in the current control flow.

## First-run reviewer setup

GovernLoop includes a localhost-only wizard for binding your own dedicated ChatGPT conversation as the reviewer.

```bash
export PYTHONPATH="$PWD/tools"
python -m governloop_runtime setup --repo owner/repository
```

The command opens a local page on `127.0.0.1`. You provide the target repository, one exact `https://chatgpt.com/c/<conversation-id>` URL, the GovernLoop Chrome CDP port (default `9233`), and the browser profile path.

**Test Connection** succeeds only when exactly one open tab matches the configured conversation ID. Zero or duplicate matches fail closed. GovernLoop never asks for or stores a ChatGPT password, cookie, session token, or OpenAI API key; login happens directly on ChatGPT.

The route is stored at:

```text
~/.governloop/relay/config.json
```

For headless use:

```bash
python -m governloop_runtime setup --repo owner/repository --no-open
```

## Quick start

GovernLoop is currently a repository-first developer tool rather than an installed package.

```bash
git clone https://github.com/liangzhipengdamon-maker/GovernLoop.git
cd GovernLoop

export PYTHONPATH="$PWD/tools"
export LINEAR_ACCESS_TOKEN="<linear-token>"

# Bind a dedicated reviewer conversation
python -m governloop_runtime setup --repo owner/repository

# Explicit scope authority
export GOVERNLOOP_SCOPE_REPOSITORY="owner/repository"
export GOVERNLOOP_AUTHORIZED_BRANCH="governloop/example-task"
export GOVERNLOOP_BASELINE_SHA="<exact-base-sha>"
export GOVERNLOOP_ALLOWED_PATHS="src/,tests/"
export GOVERNLOOP_AUTHORIZED_OPERATIONS="fix,continue,complete"
export GOVERNLOOP_ALLOW_READY_MERGE_DEPLOY="false"

# One bounded MANUAL decision step
python -m governloop_runtime run-manual \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42

# Or keep the controller alive
python -m governloop_runtime watch \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42 \
  --interval 60
```

The runtime expects an authenticated `gh` CLI. Durable LoopX refresh and Neutral Relay delivery are integration-specific dependencies; failures are surfaced rather than silently treated as success.

For the detailed walkthrough, see [`docs/QUICKSTART.md`](docs/QUICKSTART.md).

## Current CLI

```text
setup                localhost reviewer-binding wizard
run-auto             one AUTO decision step
run-manual           one MANUAL decision step
watch                persistent Controller/Watcher
report               send a status report through the Neutral Relay
final-result-review  status delivery -> independent review handoff
po-decision           bind a Product Owner decision to exact PR + HEAD
complete              record exact-HEAD accepted-completion evidence
```

Run:

```bash
PYTHONPATH=tools python -m governloop_runtime --help
```

## Naming and pre-release compatibility

`GovernLoop`, `governloop_runtime`, `GOVERNLOOP_*`, and `~/.governloop/` are the canonical v0.1 names. The pre-release `agentops_runtime` / `AGENTOPS_*` implementation remains temporarily behind a thin compatibility bridge so existing validation evidence is not discarded during the naming freeze. New integrations should use only the GovernLoop names.

See [`docs/REBRAND_MIGRATION.md`](docs/REBRAND_MIGRATION.md).

## Design principles

1. **Evidence is not authority.** CI, review, ACK, runtime state, and Builder output do not create permission.
2. **Exact binding over inference.** Repository, branch, baseline, PR, and HEAD are checked explicitly.
3. **Fail closed.** Unreadable or ambiguous control evidence blocks continuation instead of guessing.
4. **One control loop.** Avoid parallel runtimes, duplicate schedulers, and hidden authorization kernels.
5. **Agent-neutral Builder boundary.** The controller does not depend on one coding-agent vendor.
6. **Human lifecycle authority stays visible.** MANUAL checkpoints are durable waiting states.

## Repository map

- `tools/governloop_runtime/` — canonical v0.1 CLI/runtime facade and first-run setup
- `tools/agentops_runtime/` — pre-v0.1 tested core retained temporarily as a compatibility implementation
- `tools/neutral-relay/` — transport-only ChatGPT reviewer relay
- `scripts/` — supporting authorization/relay tools
- `docs/governance/CURRENT_RUNTIME_RULES.md` — canonical governance contract
- `profiles/governloop.json` — canonical project profile
- `tests/` and runtime-local tests — regression/protocol coverage

## Project maturity and limitations

GovernLoop is being released early so maintainers can inspect and improve the governance model. Current limitations include:

- no PyPI/package installer yet
- reviewer-conversation binding has a first-run wizard, but full external-project onboarding still requires Builder, Linear, and browser-runtime integration
- Linear is the currently implemented task adapter
- GitHub CLI is required for live PR evidence
- Neutral Relay and LoopX integrations are environment-specific
- the first real cross-project pilot remains release-validation evidence in progress

These limitations are documented rather than hidden behind a production-ready claim.

## Contributing

Contributions are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md), and read [`SECURITY.md`](SECURITY.md) before changing authorization, relay, scope, or lifecycle behavior.

## License

Licensed under the [Apache License 2.0](LICENSE).

---

GovernLoop is an independent open-source project and is not an official OpenAI product.
