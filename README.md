# GovernLoop

GovernLoop is a lightweight local-agent ↔ ChatGPT transport layer for real project work.

The current stable baseline focuses on one capability: a local agent sends a natural-language request through the Neutral Relay to an already-open ChatGPT conversation over Chrome DevTools Protocol (CDP), waits for the assistant turn to finish streaming, and writes the complete response to a local output file.

## Current status

**v0.1.1 — Minimal Transport Recovery, cross-project E2E verified.**

The recovery baseline was merged by PR #74 and released as `v0.1.1` after clean/new and reused-conversation relay read-back E2Es passed, followed by a final clean-conversation release smoke on `main`.

Verified path:

```text
Local Agent
  → GovernLoop Neutral Relay
  → ChatGPT Web over CDP
  → natural-language assistant response
  → relay read-back
  → local output file
```

The transport does not require ChatGPT to return `PR`, `HEAD`, `ACK`, `RESULT`, or `FINAL` fields.

## Quick Start

1. Start Chrome/Chromium with remote debugging enabled on the CDP port you want GovernLoop to use, then open the target ChatGPT conversation in that browser.
2. Confirm the target ChatGPT conversation before real transport. Do not guess or silently reuse a conversation URL that the user has not selected or previously authorized for this task. If no target conversation is already explicitly established, ask the user for the ChatGPT conversation URL before sending.
3. Add that conversation URL and CDP port to the route config for the repository.
4. Create a request file containing `REVIEW_REQUEST_ID`, `REPO`, and the ordinary natural-language task.
5. Run the Neutral Relay and read the output only after the relay exits successfully.

Example request:

```text
REVIEW_REQUEST_ID: GL-EXAMPLE-001
REPO: owner/repository

Please read this project's README and summarize what the project does in two or three sentences.
```

Example route config:

```json
{
  "routes": {
    "owner/repository": {
      "conversation_url": "https://chatgpt.com/c/<conversation-id>",
      "cdp_port": 9233
    }
  }
}
```

Run (the canonical config is used by default — no `--config-file` needed):

```bash
python3 tools/neutral-relay/neutral_relay.py \
  --request-file request.txt \
  --output-file output.md
```

On success, read `output.md`; it contains the assistant response written back by the relay itself.

`--config-file` remains an optional override. By default the relay reads
`~/.governloop/relay/config.json` (see `DEFAULT_CONFIG_PATH` in
`tools/neutral-relay/neutral_relay.py`). Pass `--config-file <path>` only when
you need a non-default route configuration.

## See GovernLoop in action

Real workflow demo: a local coding agent sends a natural-language request to ChatGPT through GovernLoop, reads the complete assistant response back through the relay, and continues the local workflow automatically.

```text
Local Agent → GovernLoop → ChatGPT → relay read-back → Local Agent
```

This is a real recorded workflow, not a simulated demo.

<video src="https://github.com/user-attachments/assets/0108f19d-c9c8-4a68-9dfe-af795c1ebe08"></video>

## Neutral Relay

Canonical implementation:

```text
tools/neutral-relay/neutral_relay.py
```

Current CLI arguments:

```text
--request-file
--output-file
--config-file   # optional; default ~/.governloop/relay/config.json
--wait-timeout   # default: 900 seconds
--dry-run
```

Required request routing fields:

```text
REVIEW_REQUEST_ID: <unique-id>
REPO: owner/repository

<ordinary natural-language task>
```

The target ChatGPT conversation must already be open in the CDP-enabled browser.

### Success condition

A transport run is successful only when the relay itself:

1. exits with code `0`,
2. prints `Success: Wrote response to ...`,
3. creates the output file, and
4. writes the complete assistant response to that file.

External CDP probes may be used for diagnosis, but do not substitute for relay read-back.

## OpenCode skill

A minimal OpenCode skill is maintained in:

```text
skills/opencode/governloop/SKILL.md
```

It documents the current Neutral Relay workflow only. Historical commands such as `governloop start`, `setup-task-scope`, and governance/authority workflows are not part of this recovery baseline.

## Session manager + checkpoint reporter

A higher-level, platform-agnostic **session manager** sits on top of the relay.
It gives agents (and humans) a `/governloop` workflow:

```text
cd <project>
/governloop            # auto-detect repo + task, auto-generate session id,
                       # ask ChatGPT URL once per session
# work normally        # agent auto-reports the five checkpoints
/governloop status     # repo/task/session/URL/last checkpoint
/governloop end        # optional FINAL_VERIFICATION + temp state cleanup
```

Key properties:

- session id `<PROJECT>-<TASK>-<YYYY-MM-DD>` is **auto-generated** — users
  never invent one;
- conversation URLs are **task/session-level state** — asked once per session,
  never persisted to the canonical routing config, never inherited across
  repos (see `docs/MULTI_PROJECT_WORKFLOW.md`);
- the five checkpoints `NEW_BLOCKER` / `UNEXPECTED_STATE` /
  `BEFORE_DESTRUCTIVE_ACTION` / `REVIEW_REQUIRED` / `FINAL_VERIFICATION` are
  reported with evidence attachments; ordinary progress is never sent;
- if the relay does not support `--attachment`, evidence is inlined into the
  message with an explicit degradation note (never a false "delivered").

Components:

```text
tools/session-manager/governloop_session.py   # CLI: new|status|bind|checkpoint|end
tools/session-manager/test_governloop_session.py
skills/workbuddy/governloop/SKILL.md          # agent-facing skill definition
docs/QUICK_START.md                            # user guide (3 commands)
docs/USAGE.md                                  # full reference
docs/MULTI_PROJECT_WORKFLOW.md                 # cross-project isolation rules
```

## Local development convention

GovernLoop development follows a simple, runtime-free workflow:

- a single canonical `main` checkout is the source of truth;
- feature and fix work happens in Git worktrees, which are retired after merge;
- there is no second clone for normal development.

This repository ships as Minimal Transport — no AgentOps lifecycle runtime or
governance state machine. See `WORKTREE_LIFECYCLE.md` (local workspace) for the
full worktree convention.

## Release line

- `v0.1.0` — original public release.
- `v0.1.1` — current stable Minimal Transport Recovery release; cross-project natural-language relay behavior verified before release.

See `docs/ops/CURRENT_STATUS.md` and `docs/ops/RELEASE_NOTES_v0.1.1.md` for the release closure record.
