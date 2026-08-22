# GovernLoop

> **Connect your local coding agent to ChatGPT as a persistent project brain.**

GovernLoop creates a two-agent workflow between ChatGPT and local coding
agents.

ChatGPT can stay above the repository as the long-lived reasoning layer for
architecture, research, review, project context, and connected tools.

The local coding agent works inside the real execution environment:
repositories, files, tests, builds, debugging, and runtime operations.

GovernLoop connects the two.

```text
                 Human
                   │
            final decisions
                   │
                   ▼
              ChatGPT Web
     Architecture · Research · Review
       Project Context · Connected Tools
                   │
               GovernLoop
                   │
                   ▼
          Local Coding Agent
      Inspect · Implement · Test · Operate
                   │
                   ▼
             Real Repository
```

The automatic loop:

```text
ChatGPT
→ GovernLoop
→ Local Agent
→ implementation + evidence
→ GovernLoop
→ ChatGPT
→ review / remediation / next decision
→ GovernLoop
→ Local Agent
```

**Stop using yourself as the copy-paste bridge between the two.**

---

## Why GovernLoop?

The real workflow problem is not tooling — it is handoff. Without a bridge,
this is what a project loop looks like:

```text
ChatGPT proposes architecture
→ human copies to coding agent
→ agent executes
→ human copies result to ChatGPT
→ ChatGPT reviews
→ human copies review back
```

In those steps the human is not making a decision. The human is acting as a
**clipboard API**.

GovernLoop removes that mechanical handoff while preserving human authority at
the decision points that actually matter.

## Why ChatGPT as the project/reasoning layer?

The two sides are not interchangeable — they are complementary.

```text
Local agent:
  terminal · filesystem · repo
  implementation · tests · build · runtime

ChatGPT workspace:
  long-lived context · architecture reasoning
  cross-task reasoning · research · review
  documents · GitHub · Linear · Google Drive
  other connected project tools
```

GovernLoop is not trying to turn both sides into identical coding agents. It
connects a **project/reasoning agent** and an **execution agent** — each doing
what it is good at.

## Reuse the ChatGPT workspace you already work in

A key design motivation: GovernLoop connects into the ChatGPT workspace the
user already works in, instead of recreating the entire upper layer as a new
API-agent stack.

The upper layer is a whole stack, not one model call:

```text
model
memory / context
research
GitHub
project management
documents
review UI
conversation history
```

GovernLoop connects into that existing workspace rather than recreating all of
it. The point is not the API pricing model — it is that the project/reasoning
layer already exists, is already maintained, and is already where the user
thinks about the project.

## What exists today

The long-term idea is a two-agent project loop.

The current stable implementation deliberately starts with a narrower
primitive: **a reliable local-agent ↔ ChatGPT checkpoint and review loop.**

As of the current stable release (`v0.1.2`), GovernLoop provides:

- session-level conversation routing (`repo → task → session → conversation`)
- five decision-relevant checkpoints
- evidence attachments
- fail-closed delivery
- Neutral Relay transport
- Chrome DevTools Protocol (CDP) interaction with an already-open ChatGPT
  conversation
- complete assistant response read-back

```text
Local Agent
  → GovernLoop Neutral Relay
  → ChatGPT Web over CDP
  → natural-language assistant response
  → relay read-back
  → local output file
```

It is deliberately not (yet) a fully autonomous general-purpose orchestration
platform. The primitive is small on purpose: get the handoff right, then build
on it.

## Send decisions, not logs

GovernLoop does not report all progress to ChatGPT. Ordinary progress stays
local.

Only state that changes the next decision crosses the bridge, through five
checkpoints:

```text
NEW_BLOCKER
UNEXPECTED_STATE
BEFORE_DESTRUCTIVE_ACTION
REVIEW_REQUIRED
FINAL_VERIFICATION
```

The rule: **send decisions, not logs.**

## Evidence is part of the loop

A local path is not evidence delivery. ChatGPT cannot see `/tmp/report.md`.

Review/checkpoint messages deliver the supporting files themselves as
attachments to the same conversation. Every attachment is checked before
upload:

```text
exists → relevant → secret scan → filename / size / sha256 → upload
```

Any attachment failure aborts the run fail-closed — never a false COMPLETE.
If the evidence did not actually arrive, the checkpoint does not claim it did.
Full contract:
[`docs/architecture/neutral-relay-checkpoint-delivery.md`](docs/architecture/neutral-relay-checkpoint-delivery.md).

## See GovernLoop in action

A real recorded workflow: a local coding agent sends a natural-language request
to ChatGPT through GovernLoop, reads the complete assistant response back
through the relay, and continues the local workflow automatically.

**This is a real recorded workflow, not a simulated demo.**

```text
Local Agent → GovernLoop → ChatGPT → relay read-back → Local Agent
```

[![GovernLoop live demo — click to watch the full 2-minute workflow](https://github.com/liangzhipengdamon-maker/GovernLoop/releases/download/v0.1.2/demo_poster.png)](https://liangzhipengdamon-maker.github.io/GovernLoop/assets/demo_v0.1.2.mp4)

*Click the image above to watch the full 2-minute recorded workflow.*

---

## Quick Start

Install once, use from any project.

### WorkBuddy fast path (`/governloop`)

```text
cd <your-project>

/governloop          # creates a session for this repo, asks for the ChatGPT
                     # conversation URL once — then just work normally
/governloop status   # optional: repo / task / session / bound URL / last checkpoint
/governloop end      # when done: optional FINAL_VERIFICATION + temp state cleanup
```

`/governloop` automatically:

- detects the current git repo and derives the task (issue id → branch → title);
- generates the session id `<PROJECT>-<TASK>-<YYYY-MM-DD>` — no manual session
  ids, no per-project routing config to maintain;
- binds the ChatGPT conversation URL **once per session** (temporary state
  only; the canonical config is never modified);
- reports the five checkpoints with evidence attachments to that conversation.
  Ordinary progress is not sent.

### Generic agent path (session manager CLI)

Any agent — Claude Code, Codex, OpenCode, or a plain local script — invokes the
**same** session manager directly:

```bash
python3 <repo>/skills/workbuddy/governloop/scripts/governloop_session.py new
python3 <repo>/skills/workbuddy/governloop/scripts/governloop_session.py bind https://chatgpt.com/c/<conversation-id>
python3 <repo>/skills/workbuddy/governloop/scripts/governloop_session.py checkpoint REVIEW_REQUIRED --message "..." --attach <evidence>
python3 <repo>/skills/workbuddy/governloop/scripts/governloop_session.py end
```

Identical session model, identical rules — same repo/task detection, auto
session id, URL once per session, five checkpoints, evidence delivery, temp
state cleanup.

Guides: [`docs/QUICK_START.md`](docs/QUICK_START.md) (3 commands, incl. the 8
most common questions), [`docs/USAGE.md`](docs/USAGE.md) (full reference),
[`docs/AGENT_INTEGRATIONS.md`](docs/AGENT_INTEGRATIONS.md) (per-agent setup),
[`docs/MULTI_PROJECT_WORKFLOW.md`](docs/MULTI_PROJECT_WORKFLOW.md) (using
GovernLoop across many projects).

> Need the low-level Neutral Relay instead (route config + `--request-file`)?
> That flow is documented in [Neutral Relay](#neutral-relay) below.

## Works with

GovernLoop is agent-agnostic. The same session model works from any local
coding agent:

| Agent | Entry point |
|---|---|
| **WorkBuddy** | `/governloop` slash command (fastest UX) |
| **OpenCode** | GovernLoop skill (`skills/opencode/governloop/`) |
| **Claude Code** | invoke the local session manager CLI |
| **Codex** | invoke the local session manager CLI |
| **Any local coding agent** | invoke the local session manager CLI or the Neutral Relay directly |

All agents share one session model — repo → task → session → conversation →
checkpoints → evidence → end — and the same rules: no per-agent permanent
routing config, conversation URLs stay session-level.

## Current stable release & reliability story

**v0.1.2 — Reliable attachment-message delivery confirmation.**

A reliability patch for Neutral Relay message delivery, especially
review/checkpoint messages that carry evidence attachments. Released as
`v0.1.2` after the full relay and session-manager test suite passed on `main`.

The story behind it: **clicking Send is not confirmed delivery.** Real browser
automation can lose a send — the button click gets swallowed by the UI and the
draft is still sitting in the composer. v0.1.2 replaced click-based success
with state-based delivery confirmation:

```text
draft still present  → one safe retry (re-click while the draft remains)
composer cleared     → SEND_PENDING — never auto-resend, never re-upload
new user turn        → DELIVERY_CONFIRMED
```

Once the composer clears, the message may already be in the server send queue
even if the page has not rendered it — resending could duplicate the message.
So the relay never sends twice on a cleared composer.

The transport does not require ChatGPT to return `PR`, `HEAD`, `ACK`,
`RESULT`, or `FINAL` fields.

Release line:

- `v0.1.0` — original public release.
- `v0.1.1` — Minimal Transport Recovery release; cross-project natural-language relay behavior verified before release.
- `v0.1.2` — current stable reliability patch for Neutral Relay delivery confirmation (strong send confirmation, SEND_PENDING, duplicate-send protection).

See [`docs/ops/CURRENT_STATUS.md`](docs/ops/CURRENT_STATUS.md) and
[`docs/ops/RELEASE_NOTES_v0.1.2.md`](docs/ops/RELEASE_NOTES_v0.1.2.md) for the
release closure record.

## Session model

Conversation binding is **session-level**, not project-permanent:

```text
repo → task → session → ChatGPT conversation
```

The user picks a ChatGPT conversation once at session start; the whole session
reuses it. When the task ends, the temporary routing state can be cleared.

This avoids the failure mode of permanently binding a project to one
conversation — a project often runs several distinct threads (design, cleanup,
a PR review, a release, a bug investigation) that should not all share one
chat.

## Neutral Relay

The Neutral Relay is the transport layer between the local agent and the
ChatGPT conversation. Canonical implementation:

```text
tools/neutral-relay/neutral_relay.py
```

Current CLI arguments:

```text
--request-file
--output-file
--config-file       # optional; default ~/.governloop/relay/config.json
--wait-timeout      # default: 900 seconds
--dry-run
--attachment        # evidence file(s) uploaded to the conversation before sending (repeatable)
--conversation-url  # session-level conversation override; never written to config
--cdp-port          # session-level CDP port override; never written to config
```

Required request routing fields:

```text
REVIEW_REQUEST_ID: <unique-id>
REPO: owner/repository

<ordinary natural-language task>
```

The target ChatGPT conversation must already be open in the CDP-enabled
browser.

Short real usage example (session-level target + evidence attachments):

```bash
python3 tools/neutral-relay/neutral_relay.py \
  --request-file request.txt \
  --output-file response.md \
  --conversation-url <session-url> \
  --attachment report.md \
  --attachment manifest.json
```

### Success condition

A transport run is successful only when the relay itself:

1. exits with code `0`,
2. prints `Success: Wrote response to ...`,
3. creates the output file, and
4. writes the complete assistant response to that file.

External CDP probes may be used for diagnosis, but do not substitute for relay
read-back.

## Agent integrations

A first-class WorkBuddy command entrypoint is maintained in
`skills/workbuddy/governloop/` (`SKILL.md`, `QUICK_START.md`,
`references/policy.md`, `scripts/governloop_session.py` + tests). Normal user
workflow: `cd <project>` → `/governloop` → work → `/governloop end`. Install
it into `~/.workbuddy/skills/governloop/` to activate the slash command.

A minimal OpenCode skill is maintained in `skills/opencode/governloop/SKILL.md`.
It documents the current Neutral Relay workflow only.

Per-agent setup: [`docs/AGENT_INTEGRATIONS.md`](docs/AGENT_INTEGRATIONS.md).

## Documentation

- [`docs/QUICK_START.md`](docs/QUICK_START.md) — user guide in 3 commands, incl. the 8 most common questions.
- [`docs/USAGE.md`](docs/USAGE.md) — full command/reference manual for the session manager.
- [`docs/AGENT_INTEGRATIONS.md`](docs/AGENT_INTEGRATIONS.md) — per-agent setup.
- [`docs/MULTI_PROJECT_WORKFLOW.md`](docs/MULTI_PROJECT_WORKFLOW.md) — cross-project isolation rules.
- [`docs/architecture/neutral-relay-checkpoint-delivery.md`](docs/architecture/neutral-relay-checkpoint-delivery.md) — checkpoint + evidence delivery contract.
- [`docs/ops/CURRENT_STATUS.md`](docs/ops/CURRENT_STATUS.md) — current repository baseline.
- [`docs/ops/RELEASE_NOTES_v0.1.2.md`](docs/ops/RELEASE_NOTES_v0.1.2.md) — v0.1.2 release closure.

## What GovernLoop is not

- **Not** an autonomous multi-agent platform, a workflow engine, a policy
  engine, or a governance authority.
- **Not** a replacement for Codex, Claude Code, OpenCode, or WorkBuddy — it
  works *with* them as the execution side.
- **Not** an implementation of GitHub / Linear / Google Drive APIs. Those
  capabilities already exist in the user's ChatGPT workspace; GovernLoop
  connects the local agent to that workspace rather than rebuilding them.

## Design principles

- **Separate execution context from review/reasoning context.** The local
  agent executes; ChatGPT reasons and reviews. They are not the same context,
  and GovernLoop keeps them separate rather than collapsing them into one
  self-review loop.
- **Small, reliable boundaries over big orchestration.** Get the loop edges
  right — who executes, who reviews, where the evidence is, whether the
  message actually arrived, which session is current, when to stop and ask —
  and the agents themselves can do a lot.
- **Send decisions, not logs.** Ordinary progress stays local.
- **Fail closed.** If evidence did not arrive or delivery is unconfirmed, do
  not report success.
- **Human authority at decision points.** The human is the final authority;
  GovernLoop removes the *mechanical* handoff, not the *meaningful* decisions.

## Feedback

Open an issue or a discussion on GitHub. GovernLoop is built out of real
project failures — if you hit a new one, that is exactly the kind of input the
project needs.

---

## Closing

One agent understands the project.
One agent operates the machine.
GovernLoop keeps them in the same loop.

```text
Reasoning
+
Execution
+
Evidence
+
Human Authority
```
