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

## Positive authority

Task intent is not positive runtime authority. Linear text, PR text, review output, Builder output, runtime state, mutable repository files, and raw process environment must not create missing authority.

Canonical positive authority is **verify-only inside GovernLoop**. The runtime contains no signing key and exposes no command/API that can mint an authority document. An external operator/control identity must provision a pre-existing OpenSSH-signed authority document through an OS-protected control channel before the Builder episode.

The control channel is resolved from the operating-system account home, not from `HOME` or `GOVERNLOOP_HOME`. The operator public key, control directory, and signed authority document must not be owned or writable by the Builder/runtime OS uid. If that ownership separation is absent, GovernLoop fails closed. This means strong local authority requires real process/credential separation; a same-uid convention or an `--operator-confirm` flag is not an authority boundary.

The signed authority binds the exact:

- task ID;
- repository;
- branch;
- full baseline SHA;
- allowed paths;
- allowed non-lifecycle operations;
- trusted reviewer GitHub identities.

`run-auto`, `run-manual`, `watch`, and the legacy compatibility core independently verify the external signature. Directly importing `agentops_runtime` does not restore raw `AGENTOPS_*` as an executable authority channel.

Raw positive `GOVERNLOOP_*` / `AGENTOPS_*` scope and trusted-reviewer values are ignored as authority. Repository profiles, task text, Builder output, and runtime state cannot fill missing signed fields. Trusted reviewer identity is positive authority too and must come from the signed operator document.

Positive scope authority never contains Ready, Merge, Close/Reopen, Tag, Release, or Deploy permission. Those remain separate action-specific authorization decisions.

## Execution mode

Before execution starts, every task must specify exactly one mode: `AUTO` or `MANUAL`.

The mode controls **when the loop pauses**. It does not expand the task scope or acceptance criteria. If the mode is missing or ambiguous, surface a decision request instead of inventing a default.

### AUTO

Keep the task loop running through the in-scope steps needed to satisfy the acceptance criteria.

```text
Linear task → Builder → GitHub → GPT Review
CHANGES_REQUESTED / NOT_PASS → Builder fixes → new code HEAD → review again
PASS → continue in scope or finish when acceptance criteria are satisfied
```

Do not stop merely because a phase, commit, push, PR update, report, or review round completed. AUTO may continue through lifecycle steps already inside the task scope; it must not invent unrelated work.

### MANUAL

The task instruction must name the checkpoint or condition where PO input is required.

Run the same Builder ↔ GitHub ↔ GPT loop until that checkpoint is reached, then report the exact state and enter `WAITING_PO_AUTH`.

`WAITING_PO_AUTH` is not Controller termination. Builder may idle/exit; Controller/Watcher stays alive until a valid PO decision arrives, then execution continues from that decision.

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

The Controller terminates only on accepted completion, closure, or cancellation.
