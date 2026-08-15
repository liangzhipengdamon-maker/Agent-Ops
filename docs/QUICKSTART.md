# GovernLoop Quick Start

GovernLoop v0.1 keeps a Local Agent in a bounded Builder → Review → Remediation loop while preserving explicit Product Owner lifecycle authority.

After installation, a coding Agent should discover the public entrypoints with:

```bash
governloop --help
```

The normal user instruction can remain simply: **Use GovernLoop for this task.**

### Normal governed task

From the target Git repository/worktree:

```text
governloop start
→ GovernLoop resolves owner/repository from git remote.origin.url
→ if task ID is already known: governloop start --task-id <task>
→ otherwise TASK_ID_REQUIRED (ask only for that one missing item)
→ existing doctor/readiness flow
→ follow exactly one next_required_action / next_required_external_action
→ existing authority / reviewer / Linear prerequisites when actually requested
→ Builder works only on the exact authorized branch/scope
→ Draft PR
→ existing GovernLoop review/remediation loop
→ AUTO completion or MANUAL WAITING_PO_AUTH
```

GovernLoop does not invent a task ID from a branch name, commit, issue text, or guess. Missing authority or evidence is never reconstructed from task text, PR text, Builder output, mutable repository files, or raw process environment variables.

### Explicit reviewer connection request

If the user explicitly asks to connect/bind GovernLoop to a ChatGPT reviewer conversation, run from the target Git repository/worktree:

```text
governloop setup
→ GovernLoop resolves owner/repository from git remote.origin.url
→ GovernLoop starts/reuses its dedicated browser runtime
→ GovernLoop launches the localhost setup wizard
→ user signs in/opens exact reviewer conversation if needed
→ paste exact https://chatgpt.com/c/... URL
→ Test Connection
→ Bind Conversation
```

Do **not** preflight Chrome launch commands, CDP ports, browser profiles, setup-server ports, relay/config paths, Linear, authority, or `doctor` before setup. Let setup report the first real blocker. If it returns `NEXT_REQUIRED_ACTION`, address exactly that one blocker and rerun the same setup command.

## 1. Install and discover GovernLoop

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

When GovernLoop is used to control another repository, install GovernLoop once. For normal governed work, run `governloop start` from the target repository/worktree. For an explicit reviewer-connection request, run `governloop setup` from the target repository/worktree.

`governloop instructions` remains available for the canonical coding-agent rules, but a normal task should not require the user to know internal doctor/repository arguments.

## 2. Normal tasks start with `start`

Run from the target repository/worktree:

```bash
governloop start
```

`start` resolves the repository from the current Git origin. If the existing task ID is already present in the coding Agent's task context, run:

```bash
governloop start --task-id AGE-123
```

If the task ID is absent, GovernLoop fails closed with exactly one blocker:

```text
status: START_BLOCKED
blocker: TASK_ID_REQUIRED
NEXT_REQUIRED_ACTION: rerun governloop start --task-id <existing-task-id> ...
```

The Agent should use an already-known task ID or ask the user only for that ID. It must not invent one.

After task ID resolution, `start` delegates to the existing read-only `doctor` readiness engine. `doctor` reports `mutations_performed: false` and returns the complete check matrix plus **exactly one** top-level next step when more work is required:

- `next_required_action` — the next local/user action; or
- `next_required_external_action` — the next Product Owner / external operator action.

Follow only that top-level action, then rerun the indicated GovernLoop command. Do not solve later blockers out of order and do not manufacture authority from reported values.

Git/GitHub command failures are summarized into concise structured details; raw command usage dumps are not part of the user-facing verdict.

## 3. Bind the ChatGPT reviewer

For an explicit reviewer-connection request, run this immediately. For a normal task, run it only when GovernLoop identifies reviewer setup as the next action:

```bash
governloop setup
```

The public wrapper resolves `owner/repository` from the current Git origin and then reuses the existing setup implementation. GovernLoop setup owns the dedicated browser runtime. It first reuses a previously configured GovernLoop runtime when the saved runtime/profile marker matches, otherwise it starts a dedicated Chrome/Chromium process using the canonical GovernLoop profile and CDP port. A live but unrelated CDP endpoint fails closed rather than being silently reused.

Then GovernLoop launches the localhost-only wizard. In the dedicated GovernLoop browser window:

1. Sign in to ChatGPT if needed.
2. Open the exact reviewer conversation.
3. Copy its `https://chatgpt.com/c/...` URL into the wizard.
4. Press **Test Connection**.
5. Press **Bind Conversation**.

The Agent should not invent Chrome commands, alternate ports/profiles, or relay paths before setup reports a blocker. If setup cannot establish the browser runtime, it returns one `SETUP_BLOCKER` and one `NEXT_REQUIRED_ACTION`; handle exactly that blocker and rerun the same setup command.

GovernLoop never receives your ChatGPT password, cookie, session token, or OpenAI API key.

## 4. Authenticate external sources

When requested by GovernLoop:

```bash
gh auth status
export LINEAR_ACCESS_TOKEN="<your-linear-token>"
```

The Linear adapter is read-only. If the task cannot be read, GovernLoop fails closed instead of inventing a task specification.

Every controlled Linear task must contain exactly one `Execution Mode: AUTO` or `Execution Mode: MANUAL`. If mode is missing or ambiguous, the Product Owner must decide it; the Agent must not select a default.

## 5. Positive authority is external and verify-only

GovernLoop **cannot mint its own positive authority**. There is no canonical `bind-authority` command.

Before a signed-authority Builder episode, an external operator/control identity provisions an OpenSSH-signed authority document through the OS-protected GovernLoop control channel. The signed payload binds the exact:

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

Interactive Local is a separate same-user task-scope mode. A previously confirmed exact task scope can be verified with `governloop task-scope-check` and reused by `doctor` diagnostically when signed authority is absent; it does not grant Ready/Merge/Release/Deploy.

Raw `GOVERNLOOP_*` / `AGENTOPS_*` scope or trusted-reviewer variables are **not positive authority**. A Local Agent must not fill missing signed fields from the task description or current worktree.

Ready, Merge, Close/Reopen, Tag, Release, and Deploy are never scope operations. They require separate lifecycle authorization.

## 6. What `doctor` verifies

The check matrix includes:

- current target Git worktree and repository origin
- verified positive authority source for the selected mode
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

For config-only checks without probing the local reviewer tab, the advanced direct command remains available:

```bash
governloop doctor \
  --task-id AGE-123 \
  --repo owner/repository \
  --no-reviewer-probe
```

## 7. First-PR bootstrap

A new user does not need to arrive with a PR already created. If `doctor` reports the pull request as `EXPECTED_GATE`, use the **already authorized** branch and baseline; do not invent new values or broaden authority.

The Builder may implement, test, and push only inside the verified scope. Then create a **Draft PR** from that exact branch. Draft PR creation is delivery evidence, not Ready/Merge authorization.

After the Draft PR exists, the public entry can include the PR number:

```bash
governloop start --task-id AGE-123 --pr 42
```

GovernLoop delegates to the same doctor checks for PR open state, head branch, base SHA, and changed-file scope.

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

Signed-authority bounded step:

```bash
governloop run-auto --task-id AGE-123 --repo owner/repository --pr 42
```

or:

```bash
governloop run-manual --task-id AGE-123 --repo owner/repository --pr 42
```

Interactive Local bounded step:

```bash
governloop interactive-local --task-id AGE-123 --repo owner/repository --pr 42
```

Keep the Controller alive where appropriate:

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

### Coding Agent starts asking for repository or internal doctor syntax

Stop. Run `governloop start` from the target repository/worktree. GovernLoop resolves the GitHub repository itself. Only a genuinely missing task ID should be requested from the user.

### Reviewer connection request turns into architecture investigation

Stop. Run `governloop setup` from the target repository/worktree. Do not preflight browser/CDP/relay/source details. Setup owns those prerequisites and reports one real blocker at a time.

### `SETUP_BLOCKER: CHROME_NOT_FOUND`

Install Google Chrome/Chromium, or set `GOVERNLOOP_BROWSER_BIN` to the browser executable, then rerun the same setup command.

### `SETUP_BLOCKER: CDP_PORT_IN_USE`

Close the unrelated process using the reported CDP port, then rerun the same setup command. Do not silently bind an unrelated browser runtime.

### `REPOSITORY_UNRESOLVED`

Run `governloop start` or `governloop setup` from the target GitHub repository/worktree. GovernLoop intentionally fails closed on unsupported or ambiguous origins rather than guessing a repository.

### `TASK_ID_REQUIRED`

Use the task ID already present in the current coding task/context. If none exists, ask the user only for that ID. Do not derive one from branch names, commits, or guesses.

### `AUTHORITY_UNBOUND` / `positive_authority: BLOCKED`

For signed-authority mode, do not export guessed scope variables and do not modify repository profiles to create authority. Wait for the external operator/Product Owner to provision the signed authority document through the protected control channel. For Interactive Local, use only an exact task scope already confirmed through the TTY confirmation flow.

### `pull_request: EXPECTED_GATE`

Complete bounded work on the exact authorized branch, push it, create a Draft PR, then rerun `governloop start --task-id <task> --pr <number>`.

### `SCOPE_BLOCKED`

Run the indicated GovernLoop command and follow its single top-level next action. Typical causes are wrong repository/branch/baseline, out-of-scope PR files, dirty unrelated worktree files, or unreadable Git/GitHub evidence.

### Reviewer binding failure inside the wizard

Follow the wizard's displayed blocker. For CDP reachability errors, close the dedicated GovernLoop Chrome window and rerun the same `governloop setup` command; do not invent a different port/profile unless setup itself reports that as the blocker.

## Canonical contract

See [`governance/CURRENT_RUNTIME_RULES.md`](governance/CURRENT_RUNTIME_RULES.md). When historical documentation conflicts with that file, the current runtime rules win.
