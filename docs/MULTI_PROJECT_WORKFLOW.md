# MULTI-PROJECT WORKFLOW

GovernLoop is **shared infrastructure**, installed once. Every project gets its
own *session state* — never its own install, and never a permanent binding to a
conversation.

## The model

```text
GovernLoop installation = shared infrastructure
        ├── relay  (tools/neutral-relay)         — one, shared
        ├── session manager (tools/session-manager) — one, shared
        └── skill (skills/*/governloop)          — one per agent platform

Project A  →  session A  →  conversation A
Project B  →  session B  →  conversation B
Project C  →  session C  →  conversation C
```

Each session is identified by `<PROJECT>-<TASK>-<YYYY-MM-DD>`, auto-generated
per repo + task. Each session binds exactly one ChatGPT conversation URL, in
*temporary* state only (`/tmp/governloop-session-<SESSION_ID>.json`).

## Hard rules (mandatory)

1. **No project permanently binds a conversation.**
   The URL is task/session-level state. It lives in temp session state, never
   in `~/.governloop/relay/config.json` (the canonical routing config holds only
   trusted route defaults, and the session manager never writes it).

2. **A new project never inherits an old session URL.**
   `new` in a different repo starts unbounded — `conversation_url` is empty
   until the user provides one for that session.

3. **Never auto-guess the most recent ChatGPT tab.**
   The agent asks the user once per session. CDP target verification is
   diagnostic only and is never used to silently pick a conversation.

4. **Never write project-specific governance into GovernLoop core.**
   Project checkpoints, repo names, issue-tracker conventions, or cleanup rules
   belong to the project, not to the shared skill/relay. The skill stays
   generic: five checkpoint types, session routing, evidence delivery.

## Switching projects (user view)

```text
cd project-a
/governloop          # session A created; ask URL once (conversation A)
# ... work ...
/governloop end      # session A closed

cd project-b
/governloop          # session B created; NEW URL asked (conversation B) — never A's
# ... work ...
/governloop end
```

## Session reuse rule

An existing session is reused **only** when:

- same repo, **and**
- same task/session, **and**
- valid temp state exists.

Otherwise a new session is created. Ambiguity (multiple states for one repo)
fails safe — the caller must disambiguate instead of guessing.

## Failure model

- No URL bound → `USER_CONVERSATION_SELECTION_REQUIRED` (exit 3). The agent
  asks once and stops.
- Attachment refused (missing / secret) or relay failure →
  `CHECKPOINT_DELIVERY_INCOMPLETE` (exit 1). Never a false COMPLETE.
- Relay without `--attachment` → evidence inlined into the message body with an
  explicit degradation note (still delivered, honestly labeled).
- `end` always removes temp state; the canonical config is never modified.
