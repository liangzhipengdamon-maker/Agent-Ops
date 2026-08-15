# GovernLoop

**Governed autonomy for coding agents.**

GovernLoop is an agent-neutral control plane that keeps coding-agent work moving through implementation, pull requests, independent review, remediation, and explicit lifecycle gates without allowing runtime state, review text, or Builder output to silently expand authority.

> Project status: **v0.1.0 pre-release**. The core AUTO/MANUAL loop, exact-HEAD review path, deterministic Scope & Action Firewall, signed-authority path, Interactive Local task-scope path, MANUAL lifecycle firewall, guided readiness doctor, and clean-room cold-start onboarding path are implemented and validated. External signed authority provisioning remains operator-managed.

GovernLoop is **not** an agent observability SDK and it is not another coding agent. It governs the tools you already use.

## First run

A new user or Local Agent should install once, then let the CLI tell it what to do instead of reading runtime source code.

```bash
git clone https://github.com/liangzhipengdamon-maker/GovernLoop.git
cd GovernLoop
python -m pip install -e .

governloop --help
governloop instructions
```

After `governloop instructions`, choose exactly one path from the user's intent:

- **Explicit reviewer connection request** — determine only the target `owner/repository`, then immediately run `governloop setup --repo owner/repository`. Do not preflight Chrome/CDP/ports/profiles, run `doctor`, or invent a manual relay/browser procedure first. Setup owns the dedicated browser runtime and reports one real blocker at a time.
- **Normal governed task** — run `governloop doctor --task-id AGE-123 --repo owner/repository` from the target repository/worktree and follow exactly its one top-level next action.

`doctor` is read-only. It reports the full readiness matrix and, when blocked, exactly one top-level next step:

- `next_required_action` — the next local/user action; or
- `next_required_external_action` — the next Product Owner / external operator action.

Follow that one action and rerun `doctor`. Do not reconstruct authority from task text, repository files, raw environment variables, or the diagnostic output itself.

For the detailed onboarding flow, see [`docs/QUICKSTART.md`](docs/QUICKSTART.md).

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

GovernLoop has two explicit positive task-scope authority sources, selected by runtime mode:

- **Signed authority (default/hardened path)** — an episode-external operator signs a bundle that binds the exact repository, branch, baseline SHA, allowed paths, allowed non-lifecycle operations, and trusted reviewer identities. GovernLoop verifies this evidence but cannot mint it.
- **Interactive Local** — a same-user/same-UID exact task-scope record is confirmed through the TTY `YES` flow and may be used as the local scope authority for `interactive-local`. It is not cryptographic proof of a separate human identity and never becomes lifecycle authority.

The runtime checks local git origin, current worktree branch, exact baseline ancestry, uncommitted contamination, and the authoritative PR changed-file set against the verified source for the selected mode. Missing or unverifiable scope authority fails closed and produces no executable Builder wake.

Raw `GOVERNLOOP_*` / legacy `AGENTOPS_*` scope values, mutable repository profiles, task text, PR text, review text, CI, ACK, setup success, and runtime state cannot create missing positive authority or lifecycle permission.

Ready, Merge, Close/Reopen, Tag, Release, and Deploy remain separate lifecycle decisions. MANUAL lifecycle exceptions require exact-bound external signed Product Owner evidence.

See [`SECURITY.md`](SECURITY.md) for the trust and threat model.

## Task execution modes

GovernLoop has two task execution modes: AUTO and MANUAL. This is separate from the authority-source choice above (`signed` versus `interactive_local`).

### AUTO

The controlled Builder → GitHub → independent-review loop continues through in-scope remediation and continuation until accepted completion evidence or a real blocker.

### MANUAL

The same loop runs until a **named checkpoint** is reached. The Controller then enters `WAITING_PO_AUTH` and stays alive while awaiting a Product Owner decision. The Watcher remains alive and does not treat unauthorized remote close/merge as a normal terminal state.

There is no LOW / MEDIUM / HIGH risk classifier in the current control flow.

## Reviewer setup

For an explicit request to connect/bind a ChatGPT reviewer, run setup immediately. For a normal task, run it when `doctor` identifies reviewer binding as the next action:

```bash
governloop setup --repo owner/repository
```

`setup` starts or reuses GovernLoop's dedicated Chrome/Chromium runtime with the canonical browser profile and CDP port, then launches the localhost-only setup wizard. The Agent should not invent a browser command, alternate port/profile, or relay configuration before setup reports a blocker.

In the wizard, sign in to ChatGPT if needed, open the exact dedicated reviewer conversation in the GovernLoop browser window, paste its `https://chatgpt.com/c/...` URL, press **Test Connection**, then **Bind Conversation**. If setup cannot establish the browser runtime, it fails closed with one `NEXT_REQUIRED_ACTION`.

GovernLoop never asks for or stores a ChatGPT password, cookie, session token, or OpenAI API key; login happens directly on ChatGPT. The route is stored at `~/.governloop/relay/config.json`.

## Positive authority

There is intentionally **no canonical `bind-authority` command**. A Builder must not create or sign its own signed-authority bundle.

The external operator provisions OpenSSH-signed authority through the OS-protected control channel. GovernLoop can verify it with:

```bash
governloop authority-check --task-id AGE-123 --repo owner/repository
```

Interactive Local uses a separately confirmed local task-scope record and does not use `authority-check` as its positive-source verifier.

## Current CLI

```text
instructions           print canonical coding-agent operating instructions
setup                  bind a dedicated ChatGPT reviewer conversation
setup-authority        render a non-authoritative request for external signed authority
setup-task-scope       confirm one exact Interactive Local task scope
authority-check        verify pre-existing external signed positive authority
task-scope-check       verify an existing Interactive Local task-scope record
doctor                 read-only readiness and guided next-action diagnostics
interactive-local      run one task step using signed authority or verified local task scope
run-auto               one signed-authority AUTO decision step
run-manual             one signed-authority MANUAL decision step
watch                  persistent Controller/Watcher
report                 send a status report through the Neutral Relay
final-result-review    status delivery -> independent review handoff
complete               write legacy non-authoritative bridge compatibility evidence
```

Run:

```bash
governloop --help
```

## Naming and pre-release compatibility

`GovernLoop`, `governloop_runtime`, `GOVERNLOOP_*`, and `~/.governloop/` are the canonical v0.1 names. The pre-release `agentops_runtime` / `AGENTOPS_*` implementation remains temporarily behind a thin compatibility bridge so existing validation evidence is not discarded during the naming freeze. New integrations should use only the GovernLoop names.

See [`docs/REBRAND_MIGRATION.md`](docs/REBRAND_MIGRATION.md).

## Design principles

1. **Evidence is not authority.** CI, review, ACK, runtime state, and Builder output do not create permission.
2. **Exact binding over inference.** Repository, branch, baseline, PR, HEAD, and lifecycle action are checked explicitly.
3. **Fail closed.** Unreadable or ambiguous control evidence blocks continuation instead of guessing.
4. **One clear next step.** Readiness diagnostics and first-run setup guide the user to one dependency-ordered action instead of speculative preflight work.
5. **One control loop.** Avoid parallel runtimes, duplicate schedulers, and hidden authorization kernels.
6. **Agent-neutral Builder boundary.** The controller does not depend on one coding-agent vendor.
7. **Human lifecycle authority stays visible.** MANUAL checkpoints are durable waiting states.

## Repository map

- `tools/governloop_runtime/` — canonical v0.1 CLI/runtime facade, setup, and doctor
- `tools/agentops_runtime/` — pre-v0.1 tested core retained temporarily as a compatibility implementation
- `tools/neutral-relay/` — transport-only ChatGPT reviewer relay
- `scripts/` — supporting authorization/relay tools
- `docs/governance/CURRENT_RUNTIME_RULES.md` — canonical governance contract
- `profiles/governloop.json` — canonical project profile
- runtime-local tests — regression/protocol coverage

## Project maturity and limitations

GovernLoop is being released early so maintainers can inspect and improve the governance model. Current limitations include:

- packaging is pre-release and not yet published on PyPI; install from a repository checkout with `python -m pip install -e .`
- external signed authority provisioning remains an operator/control-plane responsibility rather than a Builder command
- Interactive Local is a same-user/same-UID convenience trust boundary, not an OS-separated signer identity
- Linear is the currently implemented task adapter
- GitHub CLI is required for live PR evidence
- Neutral Relay and LoopX integrations are environment-specific
- clean-room first-time onboarding has been validated; a full real external-project pilot remains useful follow-up evidence rather than a claimed completed capability

These limitations are documented rather than hidden behind a production-ready claim.

## Contributing

Contributions are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md), and read [`SECURITY.md`](SECURITY.md) before changing authorization, relay, scope, or lifecycle behavior.

## License

Licensed under the [Apache License 2.0](LICENSE).

---

GovernLoop is an independent open-source project and is not an official OpenAI product.
