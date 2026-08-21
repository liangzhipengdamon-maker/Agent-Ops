# USAGE — GovernLoop session manager & checkpoint reporter

This is the full reference for the GovernLoop session manager
(`skills/workbuddy/governloop/scripts/governloop_session.py`) and its
slash-command skill (`skills/workbuddy/governloop/`). For the 60-second version
see `docs/QUICK_START.md`; for per-agent setup (WorkBuddy, OpenCode, Claude
Code, Codex, generic agents) see `docs/AGENT_INTEGRATIONS.md`.

The session manager is **agent-agnostic**: `/governloop` (WorkBuddy) and the
raw CLI (any other agent) drive the exact same session model — repo → task →
session → conversation → checkpoints → evidence → end — with no per-agent
permanent routing config.

## Commands

| Command | Behavior |
|---|---|
| `/governloop` | Create or resume a session for the current repo. Detects repo (git origin → `owner/repo`), detects task (env issue id → branch → `--title` → deterministic slug), and generates the session id `<PROJECT>-<TASK>-<YYYY-MM-DD>`. If no conversation URL is bound, prints `USER_CONVERSATION_SELECTION_REQUIRED` and asks the user once. |
| `/governloop status` | Show repo, task, session id, conversation bound (yes/no), last checkpoint, temp state path. |
| `/governloop bind <conversation-url>` | Store the ChatGPT URL in the temp session state only. Never writes the canonical config. Optionally CDP-verifies the conversation is open. |
| `/governloop checkpoint <TYPE> [--message ...\|--message-file ...] [--attach PATH ...]` | Report a review checkpoint (text + evidence attachments) to the bound conversation via the Neutral Relay. |
| `/governloop end [--final] [--attach ...]` | Send `FINAL_VERIFICATION` if `--final` and bound, then remove the temp session state. Never modifies the canonical config. |

## Session rules (mandatory)

1. The conversation URL is **task/session-level state**. Ask the user **once
   per session**; reuse it for every checkpoint in the same session; never write
   it to `~/.governloop/relay/config.json`.
2. Reuse an existing session only when: same repo + same task/session + valid
   temp state exists. Never inherit a conversation URL across unrelated
   sessions or repos (a new session starts unbounded).
3. Session state lives at `/tmp/governloop-session-<SESSION_ID>.json`
   (override with `GOVERLOOP_STATE_DIR`). Request/response/config temp files for
   checkpoints are also written there.
4. `/governloop end` removes the temp state; the canonical routing config is
   never touched.

## Checkpoint reporting

Automatically report (text + relevant evidence attachments to the bound
conversation) when any of these occur:

- `NEW_BLOCKER`
- `UNEXPECTED_STATE`
- `BEFORE_DESTRUCTIVE_ACTION`
- `REVIEW_REQUIRED`
- `FINAL_VERIFICATION`

Ordinary progress must NOT be sent to the conversation (avoid noise). Only the
five checkpoint types are sent.

Evidence attachment policy (full contract: `skills/workbuddy/governloop/references/policy.md`):

- Before attaching: file exists → relevant → secret scan → record
  filename/size/sha256. The script refuses missing files and files containing
  secret patterns (PATs, `sk-`, `AKIA`, `Bearer`, ...) — for secret-bearing
  evidence, create a `.redacted` copy and attach only that.
- Never attach: `.env`, tokens, credential backups, browser profiles, caches,
  `node_modules`, secret configs, irrelevant raw logs.
- A local path written in the text does NOT count as attachment delivery.
- Success = `TEXT_RELAY: PASS` AND all required attachments delivered; any
  attachment failure → `CHECKPOINT_DELIVERY_INCOMPLETE` (never a false
  COMPLETE), and the relay is not invoked.

### Relay attachment compatibility

`neutral_relay.py` versions differ in whether they accept `--attachment`.
`governloop_session.py` probes the relay (`--help` output) before each
checkpoint:

- **Relay supports `--attachment`** → evidence files are passed as real
  attachments.
- **Relay does not** → evidence content is inlined into the message body,
  bounded per file (`INLINE_ATTACHMENT_MAX_CHARS`), and the delivery summary
  reports `0 delivered (N inlined ...)` — an honest degradation, never a false
  "attachments delivered".

## Invocation

The agent runs the bundled script directly (the user does not do this):

```bash
python3 <repo>/skills/workbuddy/governloop/scripts/governloop_session.py <subcommand> [args]
```

Environment:

- `GOVERLOOP_STATE_DIR` — session state dir (default `/tmp`)
- `GOVERLOOP_CDP_PORT` — CDP port (default `9233`, falls back to the canonical
  config's `runtime.cdp_port`, then 9233)
- `GOVERLOOP_RELAY_PATH` — path to `neutral_relay.py` (default: auto-located in
  the same repo under `tools/neutral-relay/`, with a legacy install fallback)
- `LINEAR_ISSUE_ID` / `GITHUB_ISSUE_ID` / `ISSUE_ID` / `TASK_ID` /
  `GOVERLOOP_TASK` — task identity from the current task context (highest
  priority)

Exit codes: `0` success, `1` error (incl. `CHECKPOINT_DELIVERY_INCOMPLETE`),
`3` `USER_CONVERSATION_SELECTION_REQUIRED`.

## Task identity priority

1. Linear/GitHub issue id in the current task context
   (`LINEAR_ISSUE_ID` / `GITHUB_ISSUE_ID` / `ISSUE_ID` / `TASK_ID` / `GOVERLOOP_TASK`)
2. current branch name (`LEA-91` / `issue-128` tokens recognized)
3. explicit task title (`/governloop new --title ...`)
4. deterministic generated slug (`TASK-<hash6>`)

## Workflow for the agent

1. On `/governloop`: run `new`. If it prints
   `USER_CONVERSATION_SELECTION_REQUIRED`, ask the user for the ChatGPT
   conversation URL **once**, then run `bind <url>`. Confirm CDP target open
   before the first real checkpoint.
2. During work: when a checkpoint type occurs, run
   `checkpoint <TYPE> --message "<concise status>" --attach <evidence...>`
   (attach only relevant, secret-safe evidence; max a few files).
3. On `/governloop end`: run `end --final --attach <final-report> <manifest>`
   if a final report is appropriate, otherwise `end`. Verify the temp state file
   is gone and the canonical config was untouched.
