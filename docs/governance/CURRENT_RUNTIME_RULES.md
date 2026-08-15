# GovernLoop Current Runtime Rules

This is the single current control contract. Older governance/architecture docs are historical when they conflict with this file.

## Roles

- **Linear**: task instructions, acceptance criteria, status, dependencies.
- **GitHub**: code, PRs, reviews, technical evidence, merge state.
- **ChatGPT Web**: architecture, independent review, and decisions during execution.
- **Product Owner**: chooses the task execution mode and gives decisions at manual gates.
- **Relay**: transport only.
- **Builder**: implementation.
- **Controller/Watcher**: keeps the task loop alive across Builder exits and waiting periods.
- **LoopX/runtime state**: durable operational state only.

## Positive task-scope authority

Task intent is not positive runtime authority. Linear text, PR text, review output, Builder output, runtime state, mutable repository files, raw process environment, reviewer setup success, and relay ACK must not create missing scope or lifecycle authority.

GovernLoop supports two explicit positive **task-scope** authority sources. The selected runtime entry determines which source may be used:

### Signed authority (default / hardened path)

`run-auto`, `run-manual`, `watch`, and the legacy compatibility core require a pre-existing OpenSSH-signed authority document. GovernLoop is verify-only for this source: the runtime contains no signing key and exposes no command/API that can mint or approve the signed document.

An external operator/control identity provisions the signed authority through an OS-protected control channel. The control channel is resolved from the operating-system account home, not from `HOME` or `GOVERNLOOP_HOME`. The operator public key, control directory, and signed authority document must not be owned or writable by the Builder/runtime OS uid. If that ownership separation is absent, the signed path fails closed. Strong local signed authority therefore requires real process/credential separation.

The signed authority binds the exact:

- task ID;
- repository;
- branch;
- full baseline SHA;
- allowed paths;
- allowed non-lifecycle operations;
- trusted reviewer GitHub identities.

Directly importing `agentops_runtime` does not restore raw `AGENTOPS_*` as an executable authority channel.

### Interactive Local task scope

`interactive-local` first attempts the signed source above. If signed authority is unavailable or invalid, it may fall back only to an already-recorded `governloop-task-scope-v1` task-scope file for the exact task/repository.

That record is created by `governloop setup-task-scope` only after an interactive terminal displays the exact repository, branch, baseline SHA, optional HEAD pin, allowed paths, allowed non-lifecycle operations, and trusted reviewers and the same local user types exact `YES` on TTY stdin. Non-TTY input, piping, other answers, or a missing/invalid record fail closed.

Interactive Local is explicitly a **same-user / same-UID trust boundary**. Its `confirmation_method` and integrity hash are provenance/integrity markers, not cryptographic proof that a distinct human identity typed `YES`; a same-UID process can in principle rewrite same-user files. It must therefore not be described as equivalent to the OS-separated signed operator channel.

`doctor` preserves signed precedence and may use an already-valid Interactive Local task scope diagnostically when signed authority is absent so readiness checks can reach the next real dependency. Doctor does not create, rewrite, broaden, or promote the task scope.

### Shared limits

Raw positive `GOVERNLOOP_*` / `AGENTOPS_*` scope and trusted-reviewer values are ignored as authority. Repository profiles, task text, Builder output, setup state, CI, review text, relay ACK, and runtime state cannot fill missing signed/task-scope fields.

Positive task-scope authority—signed or Interactive Local—never contains Ready, Merge, Close/Reopen, Tag, Release, or Deploy permission. Those remain separate action-specific Product Owner lifecycle decisions. Interactive Local task scope must never be consumed as lifecycle authority.

## Task execution mode

Before execution starts, every task must specify exactly one execution mode: `AUTO` or `MANUAL`.

The execution mode controls **when the loop pauses**. It is separate from the task-scope authority source (`signed` versus `interactive_local`) and does not expand scope or acceptance criteria. If execution mode is missing or ambiguous, surface a decision request instead of inventing a default.

### AUTO

Keep the task loop running through the in-scope steps needed to satisfy the acceptance criteria.

```text
Linear task → Builder → GitHub → GPT Review
CHANGES_REQUESTED / NOT_PASS → Builder fixes → new code HEAD → review again
PASS → continue in scope or finish when acceptance criteria are satisfied
```

Do not stop merely because a phase, commit, push, PR update, report, or review round completed. AUTO may continue through in-scope implementation steps, but execution mode itself never grants lifecycle authority.

### MANUAL

The task instruction must name the checkpoint or condition where PO input is required.

Run the same Builder ↔ GitHub ↔ GPT loop until that checkpoint is reached, then report the exact state and enter `WAITING_PO_AUTH`.

`WAITING_PO_AUTH` is not Controller termination. Builder may idle/exit; Controller/Watcher stays alive until a valid PO decision arrives, then execution continues from that decision.

### MANUAL lifecycle authority

Product Owner decisions are positive authority and are **verify-only** inside GovernLoop. A Builder-written `.agent-bridge/po_decision.json`, GitHub review text, runtime state, setup state, ACK, CI result, or ordinary process environment is not executable PO authority.

The live MANUAL path accepts only an externally provisioned OpenSSH-signed PO decision from the OS-protected control channel. The signed payload is exact-bound to repository, PR, full current HEAD, and decision. A lifecycle permission additionally requires the exact `lifecycle_action`.

A generic signed `APPROVE` may resume the MANUAL implementation loop, but it does **not** authorize Ready, Merge, Close/Reopen, Tag, Release, or Deploy. An action-specific signed `APPROVE` authorizes only that exact lifecycle action on the exact bound object.

Once a MANUAL task is still active, remote `CLOSED` or `MERGED` state must pass the lifecycle guard before it can be treated as `TERMINAL`. This check does not depend on mutable `gate_report.json`; deleting, losing, or redirecting gate evidence cannot turn an unauthorized terminal mutation into normal completion. If the exact current HEAD cannot be established, the runtime blocks rather than accepting the mutation.

The Controller/Watcher is **decide-first**: it does not independently accept remote PR terminal state before the canonical runtime lifecycle guard runs. An unauthorized close/merge is surfaced as `LIFECYCLE_VIOLATION`, and the Watcher remains alive. Later authorization does not erase already-recorded violation evidence.

An explicitly completed or canceled Linear task remains accepted terminal evidence. Preventing a hostile Builder that already holds unrestricted repository-owner credentials from mutating GitHub outside GovernLoop requires separate process/credential isolation; GovernLoop does not treat possession of such credentials as runtime authorization.

## Reviewer setup and transport

Reviewer setup is configuration, not authority. An explicit user request to connect/bind a ChatGPT reviewer should run `governloop setup --repo <owner/repo>` directly rather than preflighting task readiness.

Setup owns startup/reuse of the dedicated local browser runtime and the localhost-only binding wizard. If setup cannot establish that runtime, it must fail closed with one real blocker/next action instead of requiring an Agent to invent Chrome/CDP/relay architecture.

Binding stores the exact reviewer conversation route. It does not grant task scope, Ready, Merge, Release, Deploy, completion, or any other lifecycle authority. Neutral Relay remains transport only.

## Independent review response contract

A machine-executable ChatGPT independent-review response is exact-bound to the request and uses this envelope:

```text
GOVERNLOOP_REVIEW: PASS|CHANGES_REQUESTED|NOT_PASS
REVIEW_REQUEST_ID: <exact request id>
REPO: <exact owner/repository>
PR: <exact PR number>
HEAD: <exact full current HEAD SHA>
```

`GOVERNLOOP_REVIEW` is the canonical v0.1 marker. `AGENTOPS_REVIEW` is accepted only as a pre-v0.1 compatibility marker.

Exactly one recognized review marker line is allowed in one response or formal review body. Duplicate canonical markers, duplicate legacy markers, or a canonical+legacy pair are ambiguous and fail closed as `INCOMPLETE`, even if the verdict text matches.

The executable verdict must also satisfy the trusted-reviewer and exact-current-HEAD rules. A stale HEAD, mismatched request/repository/PR/HEAD binding, missing binding, untrusted author, generic comment, or malformed verdict is not executable review evidence.

A review `PASS` is technical evidence only. It does not grant Ready, Merge, Deploy, scope expansion, or any other lifecycle authority.

## No risk matrix

There is no LOW/MEDIUM/HIGH runtime risk classifier in the main control flow.

Builder and GPT use judgment directly. If work is outside the task scope, ambiguous, or cannot be executed safely, surface a blocker or decision request instead of creating a risk tier or a new gate system.

## Acceptance and delivery

For code work, the live remote HEAD must contain the real code change. Docs-only/report-only commits, CI green, or self-declared PASS do not prove a code fix.

Delivery is fail-closed: unconfirmed send/read-back is `DELIVERY_FAILED`; ACK closes only the delivery episode, never the Controller.

The Controller terminates only on accepted completion, authorized/accepted closure, or cancellation.
