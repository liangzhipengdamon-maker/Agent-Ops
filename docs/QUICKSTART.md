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

## 3. Authenticate external sources

Authenticate GitHub CLI:

```bash
gh auth status
```

Provide a Linear token:

```bash
export LINEAR_ACCESS_TOKEN="<your-linear-token>"
```

The current Linear adapter is read-only. If the token is absent or the issue cannot be read, the runtime does not invent a task specification.

## 4. Bind explicit scope authority

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

## 5. Create a compatible task

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

## 6. Run one bounded decision step

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

## 7. Keep the controller alive

```bash
python -m agentops_runtime watch \
  --task-id AGE-123 \
  --repo owner/repository \
  --pr 42 \
  --interval 60
```

The Watcher survives Builder exits and waiting periods. It terminates only when accepted completion is evidenced or the PR/task is closed/canceled/completed.

`WAITING_PO_AUTH` is intentionally not a terminal state.

## 8. Exact-HEAD completion and PO decisions

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

## 9. Independent final-result review

AgentOps includes a helper for the project's current Neutral Relay integration:

```bash
python -m agentops_runtime final-result-review \
  --repo owner/repository \
  --pr 42 \
  --head <exact-head-sha> \
  --status-report /path/to/status-report.txt
```

The implemented contract automatically requests independent review only after a delivered `STATE: WAITING_REVIEW` status report. A `WAITING_PO_AUTH` report does not trigger review.

## 10. What to test first

For a first external pilot, choose a reversible, low-blast-radius change:

- documentation-backed implementation
- isolated UI behavior
- test integration
- small adapter change

Avoid using a first pilot for destructive data operations, production deployment, account/auth changes, or a broad refactor.

## Troubleshooting

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
