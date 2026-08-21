# GovernLoop session & checkpoint policy (reference)

Formal rules implemented by `scripts/governloop_session.py` and enforced by the
GovernLoop Neutral Relay (`neutral_relay.py`, contract
`docs/architecture/neutral-relay-checkpoint-delivery.md`).

## 1. Session routing

- The ChatGPT conversation URL is **task/session-level state**, never permanent
  project configuration.
- The user provides the URL **once per session**; every later checkpoint in the
  same session reuses it — no repeated asking.
- Persistence is allowed ONLY in temporary session state:
  `/tmp/governloop-session-<SESSION_ID>.json` (override: `GOVERLOOP_STATE_DIR`).
- Session id format: `<PROJECT>-<TASK>-<YYYY-MM-DD>` (auto-generated; the user
  never invents one).
- Reuse an existing session only when: same repo + same task/session + valid
  temp state exists.
- Never inherit a conversation URL across unrelated sessions or repos.
- `/governloop end` removes the temp state; the canonical config is never
  modified.

## 2. Review checkpoints

The following checkpoints MUST be reported through GovernLoop
(text + evidence attachments to the same bound conversation):

- `NEW_BLOCKER`
- `UNEXPECTED_STATE`
- `BEFORE_DESTRUCTIVE_ACTION`
- `REVIEW_REQUIRED`
- `FINAL_VERIFICATION`

Ordinary progress must NOT be sent (avoid noise).

## 3. Evidence attachment delivery

- Text and attachments MUST reach the **same** bound conversation (the relay is
  invoked with a temp config whose route carries the session URL).
- A local filesystem path written inside the text does NOT count as delivery.
- Success condition: `TEXT_RELAY = PASS` AND `REQUIRED_ATTACHMENTS_DELIVERED =
  PASS`.
- Any missing/failed attachment → `CHECKPOINT_DELIVERY_INCOMPLETE`; never
  report COMPLETE falsely. The skill refuses before invoking the relay.

## 4. Attachment safety

Before attaching a file:

1. file exists
2. file is relevant to the checkpoint
3. secret scan passes (PATs, `sk-`, `AKIA`, `xox*`, `Bearer`, ...)
4. record filename / size / sha256

Never attach: `.env`, PAT/API keys/tokens/passwords, credential backups,
browser profiles, caches, `node_modules`, secret-bearing config, irrelevant raw
logs. Secret-bearing evidence is only ever attached as a redacted copy
(`.redacted`).

## 5. FINAL_VERIFICATION defaults

`FINAL_VERIFICATION` requires at least: the final evidence report + a
manifest/verification artifact (+ any checkpoint-specific extra evidence).

## 6. Task identity priority

1. Linear/GitHub issue id in the current task context
   (`LINEAR_ISSUE_ID` / `GITHUB_ISSUE_ID` / `ISSUE_ID` / `TASK_ID` / `GOVERLOOP_TASK`)
2. current branch name (`LEA-91` / `issue-128` tokens recognized)
3. explicit task title (`/governloop new --title ...`)
4. deterministic generated slug (`TASK-<hash6>`)
