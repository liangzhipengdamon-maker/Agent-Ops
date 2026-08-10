# GovernLoop Quick Start

This guide demonstrates the current v0.1 pre-release runtime without hiding integration prerequisites. GovernLoop is still repository-first; it is not yet a one-command installed package.

## 1. Prerequisites

Required for the core decision loop:

- Python 3.10+
- Git
- GitHub CLI (`gh`) authenticated for the target repository
- a Linear task containing exactly one `Execution Mode: AUTO` or `Execution Mode: MANUAL`
- an existing GitHub pull request for the controlled task
- `LINEAR_ACCESS_TOKEN` in the environment

Integration-specific dependencies:

- `loopx-canary` for durable LoopX refresh-state integration
- the repository Neutral Relay for automated ChatGPT reviewer delivery
- an external Builder/runner consuming `.agent-bridge/status.json` and `.agent-bridge/findings.md`

GovernLoop does not silently emulate missing integrations. Unreadable authority or evidence is surfaced as degraded/BLOCKED rather than success.

## 2. Clone and expose the runtime

After the repository naming freeze is complete:

```bash
git clone https://github.com/liangzhipengdamon-maker/GovernLoop.git
cd GovernLoop
export PYTHONPATH="$PWD/tools"
```

Verify the canonical CLI:

```bash
python -m governloop_runtime --help
```

## 3. Bind your ChatGPT reviewer conversation

Open the dedicated Chrome runtime you intend GovernLoop to use, sign in to ChatGPT normally, and create or open one dedicated reviewer conversation. Do not provide GovernLoop your password, cookie, session token, or OpenAI API key.

Run:

```bash
python -m governloop_runtime setup --repo owner/repository
```

The setup server binds only to `127.0.0.1` on an ephemeral local port. The form asks for:

- repository: `owner/repository`
- dedicated ChatGPT conversation URL: `https://chatgpt.com/c/<conversation-id>`
- GovernLoop Chrome CDP port: default `9233`
- GovernLoop Chrome profile path: default `~/.governloop/chrome-profile`

The URL must identify one exact `/c/<id>` conversation. Generic ChatGPT home pages, shared links, GPT pages, non-HTTPS URLs, query strings, fragments, credentials-in-URL, or a different host are rejected.

### Test Connection

The wizard probes only the local Chrome DevTools endpoint:

```text
http://127.0.0.1:<cdp-port>/json/version
http://127.0.0.1:<cdp-port>/json
```

The check succeeds only when exactly one open page has the configured conversation ID.

- zero matching tabs -> fail closed (`REVIEWER_CONVERSATION_NOT_FOUND`)
- multiple matching tabs -> fail closed (`AMBIGUOUS_REVIEWER_CONVERSATION`)
- unreachable/invalid CDP -> fail closed

### Bind Conversation

The wizard atomically writes/updates:

```text
~/.governloop/relay/config.json
```

Unrelated existing config fields are preserved. The runtime marker is created under the selected browser profile. Only routing/runtime settings are stored; no ChatGPT credentials are collected.

For headless use:

```bash
python -m governloop_runtime setup \
  --repo owner/repository \
  --no-open
```

The command prints `SETUP_URL: http://127.0.0.1:<port>/`; open that loopback URL yourself.

For isolated testing:

```bash
python -m governloop_runtime setup \
  --repo owner/repository \
  --config-file /tmp/governloop-relay-config.json \
  --browser-profile /tmp/governloop-chrome-profile \
  --cdp-port 9233
```

## 4. Authenticate external sources

Authenticate GitHub CLI:

```bash
gh auth status
```

Provide a Linear token:

```bash
export LINEAR_ACCESS_TOKEN="<your-linear-token>"
```

The current Linear adapter is read-only. If the token is absent or the issue cannot be read, GovernLoop does not invent a task specification.

## 5. Bind explicit scope authority

The Scope & Action Firewall requires positive authority from the controller environment before a Builder wake can occur:

```bash
export GOVERNLOOP_SCOPE_REPOSITORY="owner/repository"
export GOVERNLOOP_AUTHORIZED_BRANCH="governloop/example-task"
export GOVERNLOOP_BASELINE_SHA="0123456789abcdef0123456789abcdef01234567"
export GOVERNLOOP_ALLOWED_PATHS="src/,tests/"
export GOVERNLOOP_AUTHORIZED_OPERATIONS="fix,continue,complete"
```

Recommended deny-side configuration:

```bash
export GOVERNLOOP_PROTECTED_REPOSITORIES="owner/production-repo,owner/other-sensitive-repo"
export GOVERNLOOP_ALLOW_READY_MERGE_DEPLOY="false"
```

Optional trusted-reviewer binding:

```bash
export GOVERNLOOP_TRUSTED_REVIEWERS="your-github-login"
```

Important properties:

- missing repository / branch / baseline / paths / operations -> fail closed
- repository mismatch -> fail closed
- wrong current worktree branch -> fail closed
- local git origin mismatch/unreadable -> fail closed
- changed PR files outside allowed paths -> fail closed
- uncommitted unrelated paths -> fail closed
- review or Builder text cannot expand these values

Establish authority **before** the Builder episode. Do not source positive authority from a mutable file controlled by the same Builder.

## 6. Create a compatible task

Minimal AUTO task:

```text
Execution Mode: AUTO

Acceptance Criteria
- implement the requested change
- tests pass
- exact current PR HEAD receives independent review
```

Minimal MANUAL task:

```text
Execution Mode: MANUAL
Checkpoint: review approval

Acceptance Criteria
- implement the requested change
- tests pass
- exact current PR HEAD receives independent review
- stop at WAITING_PO_AUTH after PASS
```

In v0.1, `review approval` maps to the review-PASS checkpoint. Unsupported checkpoint text fails closed instead of being guessed.

## 7. Run one bounded decision step

AUTO:

```bash
python -m governloop_runtime run-auto \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42
```

MANUAL:

```bash
python -m governloop_runtime run-manual \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42
```

Typical phases include `REVIEW`, `FIX`, `PASSED`, `WAITING_PO_AUTH`, `BLOCKED`, `COMPLETE`, and `TERMINAL`.

A `CHANGES_REQUESTED` / `NOT_PASS` review can wake the Builder only when the scope firewall passes.

## 8. Keep the Controller alive

```bash
python -m governloop_runtime watch \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42 \
  --interval 60
```

The Watcher survives Builder exits and waiting periods. `WAITING_PO_AUTH` is intentionally not terminal.

## 9. Exact-HEAD completion and PO decisions

A bare review PASS does not create completion evidence.

Record accepted completion:

```bash
python -m governloop_runtime complete \
  --repo owner/repository \
  --pr 42 \
  --head <exact-head-sha>
```

Bind a MANUAL Product Owner decision:

```bash
python -m governloop_runtime po-decision \
  --repo owner/repository \
  --pr 42 \
  --head <exact-head-sha> \
  --decision APPROVE
```

This resumes the control loop. It is not GitHub Ready/Merge/Deploy permission unless separate governance explicitly grants that lifecycle action.

## 10. Independent final-result review

```bash
python -m governloop_runtime final-result-review \
  --repo owner/repository \
  --pr 42 \
  --head <exact-head-sha> \
  --status-report /path/to/status-report.txt
```

Independent review is automatically requested only after a delivered `STATE: WAITING_REVIEW` report whose repo/PR/HEAD binding matches the invocation. `WAITING_PO_AUTH` does not trigger review.

## 11. Pre-release naming migration

Canonical v0.1 names are:

```text
GovernLoop
governloop_runtime
GOVERNLOOP_*
~/.governloop/
```

Existing pre-v0.1 local environments may still contain `agentops_runtime`, `AGENTOPS_*`, or `~/.agentops/`. The v0.1 branch retains a thin compatibility bridge, but new integrations should use only the canonical names. See [`REBRAND_MIGRATION.md`](REBRAND_MIGRATION.md).

## 12. What to test first

Choose a reversible, low-blast-radius pilot such as a documentation-backed implementation, isolated UI behavior, test integration, or small adapter change. Avoid destructive data operations, production deployment, account/auth changes, and broad refactors for a first pilot.

## Troubleshooting

### Setup page does not open

Run with `--no-open` and copy the printed `SETUP_URL`. The server intentionally listens only on `127.0.0.1`.

### `REVIEWER_CONVERSATION_NOT_FOUND`

Open the exact dedicated ChatGPT conversation in the Chrome runtime using the configured CDP port.

### `AMBIGUOUS_REVIEWER_CONVERSATION`

Close duplicate tabs showing the same bound conversation. GovernLoop does not choose arbitrarily.

### CDP unreachable

Confirm the GovernLoop Chrome process uses remote debugging on the configured port. Default: `9233`.

### `LINEAR_UNREADABLE`

Check `LINEAR_ACCESS_TOKEN` and the task identifier/team.

### `SCOPE_BLOCKED`

Inspect `builder.reason` and `checks`. Common causes are missing scope env, repo/branch/base mismatch, out-of-scope PR files, a dirty unrelated worktree, or an unverifiable git origin.

### `CHECKPOINT_UNEVALUABLE`

Use a supported checkpoint such as `Checkpoint: review approval`.

### LoopX degraded

LoopX refresh failure is surfaced and is not silently converted into durable-state success.

### Relay delivery failed

Delivery is fail closed. Retry the delivery path; do not reinterpret an unconfirmed send as ACKed.

## Next steps

- [`governance/CURRENT_RUNTIME_RULES.md`](governance/CURRENT_RUNTIME_RULES.md)
- [`../SECURITY.md`](../SECURITY.md)
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
