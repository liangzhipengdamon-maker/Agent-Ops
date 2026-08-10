# GovernLoop Quick Start

GovernLoop v0.1 keeps a Local Agent in a bounded Builder → Review → Remediation loop while preserving explicit Product Owner lifecycle authority.

The intended first-task flow is:

```text
Clone / expose runtime
→ bind one ChatGPT reviewer conversation
→ authenticate GitHub + Linear
→ external operator provisions signed positive authority
→ governloop doctor
→ Builder works only on the exact authorized branch/scope
→ Draft PR
→ governloop doctor --pr <number>
→ GovernLoop review/remediation loop
→ AUTO completion or MANUAL WAITING_PO_AUTH
```

Missing authority or evidence is reported. It is never reconstructed from task text, PR text, Builder output, mutable repository files, or raw process environment variables.

## 1. Prerequisites

- Python 3.10+
- Git
- GitHub CLI (`gh`) authenticated for the target repository
- `LINEAR_ACCESS_TOKEN` in the controller/operator environment
- a Linear task containing exactly one `Execution Mode: AUTO` or `Execution Mode: MANUAL`
- one dedicated ChatGPT reviewer conversation configured through GovernLoop setup
- externally signed positive authority provisioned before the Builder episode

Expose the runtime:

```bash
git clone https://github.com/liangzhipengdamon-maker/GovernLoop.git
cd GovernLoop
export PYTHONPATH="$PWD/tools"
python -m governloop_runtime --help
```

## 2. Bind the ChatGPT reviewer

Run:

```bash
python -m governloop_runtime setup --repo owner/repository
```

Use one dedicated ChatGPT conversation in the configured Chrome/CDP runtime. GovernLoop should never receive your ChatGPT password, cookie, or session token.

## 3. Authenticate external sources

```bash
gh auth status
export LINEAR_ACCESS_TOKEN="<your-linear-token>"
```

The Linear adapter is read-only. If the task cannot be read, GovernLoop fails closed instead of inventing a task specification.

## 4. Positive authority is external and verify-only

GovernLoop **cannot mint its own positive authority**. There is no canonical `bind-authority` command.

Before the Builder episode, an external operator/control identity must provision an OpenSSH-signed authority document through the OS-protected GovernLoop control channel. The signed payload binds the exact:

- task ID
- repository
- branch
- full baseline SHA
- allowed paths
- allowed non-lifecycle operations (`fix`, `continue`, `complete`)
- trusted reviewer GitHub identities

The runtime verifies this evidence with:

```bash
python -m governloop_runtime authority-check \
  --task-id AGE-123 \
  --repo owner/repository
```

Raw `GOVERNLOOP_*` / `AGENTOPS_*` scope or trusted-reviewer variables are **not positive authority**. A Local Agent must not fill missing signed fields from the task description or current worktree.

Ready, Merge, Close/Reopen, Tag, Release, and Deploy are never scope operations. They require separate lifecycle authorization.

## 5. Run `doctor` before Builder work

```bash
python -m governloop_runtime doctor \
  --task-id AGE-123 \
  --repo owner/repository
```

`doctor` is read-only and reports `mutations_performed: false`. It checks:

- external signed positive authority and trusted reviewers
- git origin, exact branch, and bound baseline
- dirty worktree paths against allowed scope
- GitHub CLI authentication
- Linear task readability and execution mode
- configured ChatGPT reviewer/CDP reachability
- optional PR branch/base/file-scope binding

Overall states:

- `READY` — all checks for the supplied stage pass
- `BOOTSTRAP_REQUIRED` — only an expected first-task gate remains, normally the first Draft PR
- `BLOCKED` — a prerequisite is absent, unreadable, or mismatched

For config-only checks without probing the local reviewer tab:

```bash
python -m governloop_runtime doctor \
  --task-id AGE-123 \
  --repo owner/repository \
  --no-reviewer-probe
```

## 6. First-PR bootstrap

A new user does not need to arrive with a PR already created. If `doctor` reports the pull request as `EXPECTED_GATE`, use the **already authorized** branch and baseline; do not invent new values or broaden authority.

The Builder may implement, test, and push only inside the signed scope. Then create a **Draft PR** from that exact branch. Draft PR creation is delivery evidence, not Ready/Merge authorization.

After the Draft PR exists:

```bash
python -m governloop_runtime doctor \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42
```

GovernLoop checks that the PR is open, its head branch and base SHA match the signed authority, and all changed files remain in scope.

## 7. Task modes

AUTO example:

```text
Execution Mode: AUTO

Acceptance Criteria
- implement the requested bounded change
- tests pass
- exact current PR HEAD receives independent review
```

MANUAL example:

```text
Execution Mode: MANUAL
Checkpoint: review approval

Acceptance Criteria
- implement the requested bounded change
- tests pass
- exact current PR HEAD receives independent review
- stop at WAITING_PO_AUTH after PASS
```

If mode is missing or ambiguous, GovernLoop blocks rather than choosing one.

## 8. Run the loop

One bounded step:

```bash
python -m governloop_runtime run-auto --task-id AGE-123 --repo owner/repository --pr 42
```

or:

```bash
python -m governloop_runtime run-manual --task-id AGE-123 --repo owner/repository --pr 42
```

Keep the Controller alive:

```bash
python -m governloop_runtime watch \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42 \
  --interval 600
```

`WAITING_PO_AUTH` is not terminal. The Watcher remains alive and lifecycle mutations remain frozen unless the exact action is separately authorized by valid external signed PO evidence.

## 9. Independent review envelope

Machine-executable independent review is exact-bound:

```text
GOVERNLOOP_REVIEW: PASS|CHANGES_REQUESTED|NOT_PASS
REVIEW_REQUEST_ID: <exact request id>
REPO: <exact owner/repository>
PR: <exact PR number>
HEAD: <exact full current HEAD SHA>
```

`GOVERNLOOP_REVIEW` is canonical. `AGENTOPS_REVIEW` is pre-v0.1 compatibility only. Duplicate or mixed markers fail closed. Review PASS is technical evidence only; it never grants Ready, Merge, Release, or Deploy.

## 10. Completion and Product Owner decisions

A bare review PASS does not create completion evidence. Accepted COMPLETE requires exact-bound external signed completion evidence.

For MANUAL tasks, Product Owner decisions are also verify-only external signed evidence. Generic APPROVE may resume the loop but does not authorize lifecycle actions. Ready/Merge/Close/Tag/Release/Deploy require exact action-specific authorization.

Legacy bridge files such as `.agent-bridge/completion.json` or `.agent-bridge/po_decision.json` are non-authoritative compatibility evidence.

## Troubleshooting

### `AUTHORITY_UNBOUND`

Do not export guessed scope variables and do not modify repository profiles to create authority. Ask the external operator/Product Owner to provision the signed authority document through the protected control channel.

### `pull_request: EXPECTED_GATE`

Complete bounded work on the exact authorized branch, push it, create a Draft PR, then rerun `doctor --pr <number>`.

### `SCOPE_BLOCKED`

Run `doctor`. Typical causes are wrong repository/branch/baseline, out-of-scope PR files, dirty unrelated worktree files, or unreadable Git/GitHub evidence.

### Reviewer binding failure

Run setup again and ensure exactly one configured ChatGPT reviewer conversation is open in the configured Chrome/CDP runtime.

## Canonical contract

See [`governance/CURRENT_RUNTIME_RULES.md`](governance/CURRENT_RUNTIME_RULES.md). When historical documentation conflicts with that file, the current runtime rules win.
