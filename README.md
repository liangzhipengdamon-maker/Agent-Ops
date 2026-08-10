# AgentOps Control Plane

**Governed, agent-neutral control loops for long-running software work.**

AgentOps keeps a coding-agent workflow moving through implementation, pull requests, independent review, remediation, and human decision gates without letting runtime state, review text, or the Builder silently expand authority.

> Project status: **v0.1.0 pre-release**. The core runtime loop and deterministic scope/action firewall are implemented and tested. Packaging and external onboarding are still early-stage.

AgentOps is **not** an agent observability SDK and it is not another coding agent. It is a thin control plane around the tools you already use.

## Why AgentOps

Coding agents can implement a task quickly, but long-running work introduces a different problem: **who is allowed to do what, against which exact repository/branch/HEAD, and what happens after an agent exits or a reviewer asks for changes?**

AgentOps separates those responsibilities:

- **Builder** implements changes.
- **GitHub** is the source of truth for code, PR state, CI, and exact review HEAD.
- **Linear** supplies task instructions, acceptance criteria, mode, and status.
- **Independent reviewer** evaluates the actual current PR HEAD.
- **Controller/Watcher** keeps the loop alive across Builder exits and waiting periods.
- **Neutral Relay** transports review/status messages but has no authority.
- **LoopX/runtime state** stores operational state but has no authorization authority.
- **Product Owner** retains lifecycle decisions at MANUAL gates.

The canonical runtime contract is [`docs/governance/CURRENT_RUNTIME_RULES.md`](docs/governance/CURRENT_RUNTIME_RULES.md).

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

A review `PASS` is technical evidence. It is **not** implicit permission to broaden task scope or perform Ready / Merge / Deploy.

## Safety model

The v0.1 runtime includes a deterministic Scope & Action Firewall at the Builder wake boundary.

Authorization-bearing scope must be provided explicitly from an out-of-episode source:

- exact repository
- exact authorized branch
- exact baseline SHA
- allowed path prefixes
- allowed operations

The firewall also checks the actual local git origin, current worktree branch, uncommitted contamination, and the authoritative PR changed-file set. Missing or unverifiable authority fails closed and produces no executable Builder wake.

Examples of rejected conditions include:

- wrong repository, branch, or baseline
- path traversal / absolute paths / wildcard broadening
- committed or uncommitted changes outside allowed paths
- disallowed operations
- unreadable PR changed-file evidence or local git state
- task/scope switching during an episode
- implied Ready / Merge / Deploy authority from review, CI, ACK, runtime state, or Builder instructions

See [`SECURITY.md`](SECURITY.md) for the trust and threat model.

## Execution modes

AgentOps intentionally has only two runtime modes.

### AUTO

The controlled Builder -> GitHub -> independent-review loop continues through in-scope remediation and continuation until the task reaches accepted completion or a real blocker.

### MANUAL

The same loop runs until a **named checkpoint** is reached. The Controller then enters `WAITING_PO_AUTH` and stays alive while awaiting a Product Owner decision.

There is no LOW / MEDIUM / HIGH risk classifier in the current control flow.

## Quick start

AgentOps is currently a repository-first developer tool rather than an installed package. A minimal controlled run requires Python, GitHub CLI, a readable Linear task, an existing GitHub PR, and explicit scope authority.

```bash
git clone https://github.com/liangzhipengdamon-maker/Agent-Ops.git
cd Agent-Ops

export PYTHONPATH="$PWD/tools"
export LINEAR_ACCESS_TOKEN="<linear-token>"

export AGENTOPS_SCOPE_REPOSITORY="owner/repository"
export AGENTOPS_AUTHORIZED_BRANCH="agentops/example-task"
export AGENTOPS_BASELINE_SHA="<exact-base-sha>"
export AGENTOPS_ALLOWED_PATHS="src/,tests/"
export AGENTOPS_AUTHORIZED_OPERATIONS="fix,continue,complete"
export AGENTOPS_ALLOW_READY_MERGE_DEPLOY="false"

# One bounded decision step
python -m agentops_runtime run-manual \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42

# Or keep the controller alive
python -m agentops_runtime watch \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42 \
  --interval 60
```

The production runtime also expects an authenticated `gh` CLI. Durable LoopX refresh and Neutral Relay delivery are optional/integration-specific dependencies; failures are surfaced instead of silently treated as success.

For a detailed walkthrough, see [`docs/QUICKSTART.md`](docs/QUICKSTART.md).

## Current CLI

```text
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
PYTHONPATH=tools python -m agentops_runtime --help
```

## Design principles

1. **Evidence is not authority.** CI, review, ACK, runtime state, and Builder output do not create permission.
2. **Exact binding over inference.** Repository, branch, baseline, PR, and HEAD are checked explicitly.
3. **Fail closed.** Unreadable or ambiguous control evidence blocks continuation instead of guessing.
4. **One control loop.** AgentOps avoids parallel runtimes, duplicate schedulers, and hidden authorization kernels.
5. **Agent-neutral Builder boundary.** The controller hands off work through a small bridge contract rather than depending on one coding-agent vendor.
6. **Human lifecycle authority stays visible.** MANUAL checkpoints are first-class, durable waiting states.

## Repository map

- `tools/agentops_runtime/` — current AUTO/MANUAL runtime, Controller/Watcher, review intake, relay integration, scope firewall
- `scripts/` — supporting authorization/relay tools
- `docs/governance/CURRENT_RUNTIME_RULES.md` — canonical current governance contract
- `docs/governance/` — governance documentation; older material is historical when it conflicts with the canonical contract
- `tests/` and runtime-local tests — regression and protocol coverage

## Project maturity and limitations

AgentOps is being released early so other maintainers can inspect and improve the governance model. Current limitations include:

- no PyPI/package installer yet
- external-project onboarding is not yet a one-command experience
- Linear is the currently implemented task adapter
- GitHub CLI is used for live PR evidence
- Neutral Relay and LoopX integrations are environment-specific
- the first real cross-project pilot is part of the v0.1 release validation

These are intentionally documented rather than hidden behind a "production-ready" claim.

## Contributing

Contributions are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md), and please read [`SECURITY.md`](SECURITY.md) before proposing changes to authorization, relay, scope, or lifecycle behavior.

## Security

Please do not publish suspected authorization bypasses or secret-bearing logs in a public issue. Follow the private reporting guidance in [`SECURITY.md`](SECURITY.md).

## License

Licensed under the [Apache License 2.0](LICENSE).

---

AgentOps is an independent open-source project and is not an official OpenAI product.