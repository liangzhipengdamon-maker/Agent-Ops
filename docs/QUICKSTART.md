# AgentOps Quick Start

This guide demonstrates the current v0.1 runtime as it exists today. AgentOps is not yet packaged as a one-command installer; the goal of this walkthrough is to make the real control contract reproducible without hiding integration prerequisites.

## 1. Prerequisites

Required for the core decision loop:

- Python 3.10+
- Git
- GitHub CLI (`gh`) authenticated for the target repository
- a Linear task whose description contains an explicit `Execution Mode: AUTO` or `Execution Mode: MANUAL`
- an existing GitHub pull request for the controlled task
- `LINEAR_ACCESS_TOKEN` in the environment

Integration-specific dependencies:

- `loopx-canary` if you want durable LoopX refresh-state integration
- the project Neutral Relay setup if you want automated status/report delivery to an independent reviewer
- an external Builder/runner that consumes `.agent-bridge/status.json` and `.agent-bridge/findings.md`

AgentOps deliberately does not silently emulate missing integrations. Unreadable authority or evidence is surfaced as degraded/BLOCKED rather than treated as success.

## 2. Clone and expose the runtime package

```bash
git clone https://github.com/liangzhipengdamon-maker/Agent-Ops.git
cd Agent-Ops
export PYTHONPATH="$PWD/tools"
```

Verify the CLI:

```bash
python -m agentops_runtime --help
```

## 3. Bind your ChatGPT reviewer conversation

Open the dedicated Chrome runtime you intend AgentOps to use, sign in to ChatGPT normally, and create or open a dedicated reviewer conversation. Do not give AgentOps your password, cookie, session token, or OpenAI API key.

Then run:

```bash
python -m agentops_runtime setup --repo owner/repository
```

AgentOps starts a setup server bound only to `127.0.0.1` on an ephemeral local port and opens the setup page in your browser. The form asks for:

- repository: `owner/repository`
- dedicated ChatGPT conversation URL: `https://chatgpt.com/c/<conversation-id>`
- AgentOps Chrome CDP port: default `9233`
- AgentOps Chrome profile path: default `~/.agentops/chrome-profile`

The conversation URL is canonicalized and must identify one exact `/c/<id>` ChatGPT conversation. Generic ChatGPT home pages, shared links, GPT pages, non-HTTPS URLs, query strings, fragments, or a different host are rejected.

### Test Connection

Before binding, click **Test Connection**. The wizard probes only the local Chrome DevTools endpoint:

```text
http://127.0.0.1:<cdp-port>/json/version
http://127.0.0.1:<cdp-port>/json
```

The check succeeds only when exactly one open page has the same ChatGPT conversation ID as the URL you entered.

- zero matching tabs -> fail closed (`REVIEWER_CONVERSATION_NOT_FOUND`)
- multiple matching tabs -> fail closed (`AMBIGUOUS_REVIEWER_CONVERSATION`)
- unreachable/invalid CDP -> fail closed

The wizard does not select a generic ChatGPT tab and does not guess between duplicates.

### Save

**Bind Conversation** writes/updates:

```text
~/.agentops/relay/config.json
```

The write is atomic, unrelated existing config fields are preserved, and the runtime marker is created under the selected browser profile. The saved fields are local routing/runtime settings only; no ChatGPT credentials are collected or stored.

For a machine where you do not want AgentOps to open a browser tab automatically:

```bash
python -m agentops_runtime setup \
  --repo owner/repository \
  --no-open
```

The command prints `SETUP_URL: http://127.0.0.1:<port>/`; open that loopback URL yourself.

For tests or isolated configurations you can use:

```bash
python -m agentops_runtime setup \
  --repo owner/repository \
  --config-file /tmp/agentops-relay-config.json \
  --browser-profile /tmp/agentops-chrome-profile \
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

The current Linear adapter is read-only. If the token is absent or the issue cannot be read, the runtime does not invent a task specification.

## 5. Bind explicit scope authority

The Scope & Action Firewall requires these authorization-bearing values from the controller's environment before a Builder wake can occur:

```bash
export AGENTOPS_SCOPE_REPOSITORY="owner/repository"
export AGENTOPS_AUTHORIZED_BRANCH="agentops/example-task"
export AGENTOPS_BASELINE_SHA="0123456789abcdef0123456789abcdef01234567"
export AGENTOPS_ALLOWED_PATHS="src/,tests/"
export AGENTOPS_AUTHORIZED_OPERATIONS="fix,continue,complete"
```

Recommended deny-side configuration:

```bash
export AGENTOPS_PROTECTED_REPOSITORIES="owner/production-repo,owner/other-sensitive-repo"
export AGENTOPS_ALLOW_READY_MERGE_DEPLOY="false"
```

Important properties:

- missing repository / branch / baseline / paths / operations -> fail closed
- repository mismatch -> fail closed
- wrong current worktree branch -> fail closed
- local git origin mismatch/unreadable -> fail closed
- changed PR files outside the allowed paths -> fail closed
- uncommitted unrelated paths -> fail closed
- review or Builder text cannot expand these values

The environment is intended to be established by the controller/launcher **before** the Builder episode. Do not source these values from a file that the controlled Builder can rewrite.

## 6. Create a compatible task

The current task adapter reads the task description from Linear. For portable task definitions, use the explicit field syntax below rather than relying on fallback marker detection.

Minimal AUTO example:

```text
Execution Mode: AUTO

Acceptance Criteria
- implement the requested change
- tests pass
- exact current PR HEAD receives independent review
```

Minimal MANUAL example:

```text
Execution Mode: MANUAL
Checkpoint: review approval

Acceptance Criteria
- implement the requested change
- tests pass
- exact current PR HEAD receives independent review
- stop at WAITING_PO_AUTH after PASS
```

The supported MANUAL checkpoint in v0.1 maps `review approval` to a review-PASS stage. Unsupported checkpoint text fails closed instead of being guessed.

## 7. Run one bounded decision step

Assume:

- task: `AGE-123`
- repo: `owner/repository`
- PR: `42`

AUTO:

```bash
python -m agentops_runtime run-auto \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42
```

MANUAL:

```bash
python -m agentops_runtime run-manual \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42
```

The command emits a machine-readable outcome. Typical phases include:

- `REVIEW`
- `FIX`
- `PASSED`
- `WAITING_PO_AUTH`
- `BLOCKED`
- `COMPLETE`
- `TERMINAL`

If a review is `CHANGES_REQUESTED` / `NOT_PASS` and the scope firewall passes, the runtime writes a Builder wake to `.agent-bridge`.

## 8. Keep the controller alive

```bash
python -m agentops_runtime watch \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42 \
  --interval 60
```

The Watcher survives Builder exits and waiting periods. It terminates only when accepted completion is evidenced or the PR/task is closed/canceled/completed.

`WAITING_PO_AUTH` is intentionally not a terminal state.

## 9. Exact-HEAD completion and PO decisions

A bare review PASS does not create completion evidence.

When acceptance is genuinely satisfied, the Builder/controller can bind completion to the exact PR + HEAD:

```bash
python -m agentops_runtime complete \
  --repo owner/repository \
  --pr 42 \
  --head <exact-head-sha>
```

At a MANUAL gate, a Product Owner decision can be bound to that exact PR + HEAD:

```bash
python -m agentops_runtime po-decision \
  --repo owner/repository \
  --pr 42 \
  --head <exact-head-sha> \
  --decision APPROVE
```

This decision resumes the control loop. It should not be confused with GitHub Ready/Merge/Deploy authorization unless your external governance explicitly grants that action separately.

## 10. Independent final-result review

AgentOps includes a helper for the project's current Neutral Relay integration:

```bash
python -m agentops_runtime final-result-review \
  --repo owner/repository \
  --pr 42 \
  --head <exact-head-sha> \
  --status-report /path/to/status-report.txt
```

The implemented contract automatically requests independent review only after a delivered `STATE: WAITING_REVIEW` status report. A `WAITING_PO_AUTH` report does not trigger review.

## 11. What to test first

For a first external pilot, choose a reversible, low-blast-radius change:

- documentation-backed implementation
- isolated UI behavior
- test integration
- small adapter change

Avoid using a first pilot for destructive data operations, production deployment, account/auth changes, or a broad refactor.

## Troubleshooting

### Setup page does not open

Run with `--no-open` and copy the printed `SETUP_URL` into a browser. The setup server intentionally listens only on `127.0.0.1`; it is not remotely accessible.

### `REVIEWER_CONVERSATION_NOT_FOUND`

Make sure the exact dedicated ChatGPT conversation is open in the Chrome runtime using the configured CDP port. A different ChatGPT conversation does not count.

### `AMBIGUOUS_REVIEWER_CONVERSATION`

Close duplicate tabs that show the same bound conversation and retry. AgentOps refuses to choose one arbitrarily.

### CDP unreachable

Confirm the AgentOps Chrome process was started with remote debugging on the same port configured in the wizard. The default is `9233`.

### `LINEAR_UNREADABLE`

Check `LINEAR_ACCESS_TOKEN` and that the task identifier belongs to a supported team key.

### `SCOPE_BLOCKED`

Inspect the returned `builder.reason` / `checks`. Common causes are missing scope env, repo/branch/base mismatch, changed files outside allowed paths, a dirty unrelated worktree, or an unverifiable git origin.

### `CHECKPOINT_UNEVALUABLE`

Use an explicitly supported MANUAL checkpoint such as `Checkpoint: review approval`. The v0.1 parser does not interpret arbitrary release/deploy checkpoint text.

### LoopX degraded

The current controller surfaces LoopX refresh failure. This does not silently turn into successful durable-state evidence.

### Relay delivery failed

Delivery is fail closed. Retry the delivery path; do not manually reinterpret an unconfirmed send as ACKed.

## Next steps

- Read the canonical rules: [`governance/CURRENT_RUNTIME_RULES.md`](governance/CURRENT_RUNTIME_RULES.md)
- Read the security model: [`../SECURITY.md`](../SECURITY.md)
- Read contribution rules: [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
