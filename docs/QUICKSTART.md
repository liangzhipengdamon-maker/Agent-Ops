# GovernLoop Quick Start

GovernLoop v0.1 keeps a Local Agent in a bounded Builder → Review → Remediation loop while preserving explicit Product Owner lifecycle authority.

The intended first-task flow is:

```text
clone/install GovernLoop
→ governloop doctor
→ follow exactly one next_required_action
→ external operator provisions signed positive authority when requested
→ bind one ChatGPT reviewer conversation
→ authenticate GitHub + Linear
→ Builder works only on the exact authorized branch/scope
→ Draft PR
→ governloop doctor --pr <number>
→ GovernLoop review/remediation loop
→ AUTO completion or MANUAL WAITING_PO_AUTH
```

Missing authority or evidence is reported. It is never reconstructed from task text, PR text, Builder output, mutable repository files, or raw process environment variables.

## 1. Install and launch GovernLoop

Required locally:

- Python 3.10+
- Git
- GitHub CLI (`gh`)

For the current repository-first v0.1 pre-release, use this canonical installation path:

```bash
git clone https://github.com/liangzhipengdamon-maker/GovernLoop.git
cd GovernLoop
python -m pip install -e .
governloop --help
```

After installation, use the `governloop` command. You should not copy individual Python modules, reconstruct compatibility dependencies, or set `PYTHONPATH` manually.

When GovernLoop is used to control another repository, install GovernLoop once and run `governloop doctor ...` from the target repository/worktree.

## 2. Start with `doctor`

Run the readiness command before trying to infer the workflow from source code:

```bash
governloop doctor \
  --task-id AGE-123 \
  --repo owner/repository
```

`doctor` is read-only and reports `mutations_performed: false`. It returns the complete check matrix plus **exactly one** top-level next step when more work is required:

- `next_required_action` — the next local/user action; or
- `next_required_external_action` — the next Product Owner / external operator action.

Follow only that top-level action, then rerun `doctor`. Do not solve later blockers out of order and do not manufacture authority from the reported values.

Example when run outside the target worktree:

```text
status: BLOCKED
next_required_action:
  check: git_repository
  action: clone/open the target repository and rerun doctor from that worktree
```

Example after the target worktree is open but external authority is missing:

```text
status: BLOCKED
next_required_external_action:
  check: positive_authority
  action: external operator must provision a valid signed authority document ...
```

Git/GitHub command failures are summarized into concise structured details; raw command usage dumps are not part of the user-facing verdict.

## 3. Bind the ChatGPT reviewer

When `doctor` identifies reviewer setup as the next action, run:

```bash
governloop setup --repo owner/repository
```

Use one dedicated ChatGPT conversation in the configured Chrome/CDP runtime. GovernLoop should never receive your ChatGPT password, cookie, or session token.

## 4. Authenticate external sources

When requested by `doctor`:

```bash
gh auth status
export LINEAR_ACCESS_TOKEN="<your-linear-token>"
```

The Linear adapter is read-only. If the task cannot be read, GovernLoop fails closed instead of inventing a task specification.

Every controlled Linear task must contain exactly one `Execution Mode: AUTO` or `Execution Mode: MANUAL`. If mode is missing or ambiguous, the Product Owner must decide it; the Agent must not select a default.

## 5. Positive authority is external and verify-only

GovernLoop **cannot mint its own positive authority**. There is no canonical `bind-authority` command.

Before the Builder episode, an external operator/control identity must provision an OpenSSH-signed authority document through the OS-protected GovernLoop control channel. The signed payload binds the exact:

- task ID
- repository
- branch
- full baseline SHA
- allowed paths
- allowed non-lifecycle operations (`fix`, `continue`, `complete`)
- trusted reviewer GitHub identities

The runtime can only verify this evidence:

```bash
governloop authority-check \
  --task-id AGE-123 \
  --repo owner/repository
```

Raw `GOVERNLOOP_*` / `AGENTOPS_*` scope or trusted-reviewer variables are **not positive authority**. A Local Agent must not fill missing signed fields from the task description or current worktree.

Ready, Merge, Close/Reopen, Tag, Release, and Deploy are never scope operations. They require separate lifecycle authorization.

## 6. What `doctor` verifies

The check matrix includes:

- current target Git worktree and repository origin
- external signed positive authority and trusted reviewers
- exact authorized branch and baseline
- exact baseline ancestry of current HEAD
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
governloop doctor \
  --task-id AGE-123 \
  --repo owner/repository \
  --no-reviewer-probe
```

## 7. First-PR bootstrap

A new user does not need to arrive with a PR already created. If `doctor` reports the pull request as `EXPECTED_GATE`, use the **already authorized** branch and baseline; do not invent new values or broaden authority.

The Builder may implement, test, and push only inside the signed scope. Then create a **Draft PR** from that exact branch. Draft PR creation is delivery evidence, not Ready/Merge authorization.

After the Draft PR exists:

```bash
governloop doctor \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42
```

GovernLoop checks that the PR is open, its head branch and base SHA match the signed authority, and all changed files remain in scope.

## 8. Task modes

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

## 9. Run the loop

One bounded step:

```bash
governloop run-auto --task-id AGE-123 --repo owner/repository --pr 42
```

or:

```bash
governloop run-manual --task-id AGE-123 --repo owner/repository --pr 42
```

Keep the Controller alive:

```bash
governloop watch \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42 \
  --interval 600
```

`WAITING_PO_AUTH` is not terminal. The Watcher remains alive and lifecycle mutations remain frozen unless the exact action is separately authorized by valid external signed PO evidence.

## 10. Independent review envelope

Machine-executable independent review is exact-bound:

```text
GOVERNLOOP_REVIEW: PASS|CHANGES_REQUESTED|NOT_PASS
REVIEW_REQUEST_ID: <exact request id>
REPO: <exact owner/repository>
PR: <exact PR number>
HEAD: <exact full current HEAD SHA>
```

`GOVERNLOOP_REVIEW` is canonical. `AGENTOPS_REVIEW` is pre-v0.1 compatibility only. Duplicate or mixed markers fail closed. Review PASS is technical evidence only; it never grants Ready, Merge, Release, or Deploy.

## 11. Completion and Product Owner decisions

A bare review PASS does not create completion evidence. Accepted COMPLETE requires exact-bound external signed completion evidence.

For MANUAL tasks, Product Owner decisions are also verify-only external signed evidence. Generic APPROVE may resume the loop but does not authorize lifecycle actions. Ready/Merge/Close/Tag/Release/Deploy require exact action-specific authorization.

Legacy bridge files such as `.agent-bridge/completion.json` or `.agent-bridge/po_decision.json` are non-authoritative compatibility evidence.

## Troubleshooting

### `git_repository: BLOCKED`

Open or clone the target repository and rerun `doctor` from that worktree. Do not copy GovernLoop Python modules into a temporary directory as a substitute for installation or a target worktree.

### `AUTHORITY_UNBOUND` / `positive_authority: BLOCKED`

Do not export guessed scope variables and do not modify repository profiles to create authority. Wait for the external operator/Product Owner to provision the signed authority document through the protected control channel.

### `pull_request: EXPECTED_GATE`

Complete bounded work on the exact authorized branch, push it, create a Draft PR, then rerun `doctor --pr <number>`.

### `SCOPE_BLOCKED`

Run `doctor` and follow its single top-level next action. Typical causes are wrong repository/branch/baseline, out-of-scope PR files, dirty unrelated worktree files, or unreadable Git/GitHub evidence.

### Reviewer binding failure

Run setup again and ensure exactly one configured ChatGPT reviewer conversation is open in the configured Chrome/CDP runtime.

## Canonical contract

See [`governance/CURRENT_RUNTIME_RULES.md`](governance/CURRENT_RUNTIME_RULES.md). When historical documentation conflicts with that file, the current runtime rules win.
