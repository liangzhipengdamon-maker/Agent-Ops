# GovernLoop

> **Connect your local coding agent to ChatGPT as a persistent project brain.**

GovernLoop creates a two-agent workflow between **ChatGPT** and **local coding agents**.

ChatGPT can stay above the repository as the long-lived reasoning layer for architecture, research, review, project context, and connected tools. The local coding agent works inside the real execution environment: repositories, files, tests, builds, debugging, and runtime operations.

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

**Stop using yourself as the copy-paste bridge between the two.**

## Why GovernLoop?

Without a bridge, a real project loop often looks like this:

```text
ChatGPT proposes architecture
→ human copies to coding agent
→ agent executes
→ human copies result to ChatGPT
→ ChatGPT reviews
→ human copies review back
```

In those steps the human is not making a decision. The human is acting as a **clipboard API**.

GovernLoop removes that mechanical handoff while preserving human authority at the decision points that matter.

## Two complementary layers

The two sides are intentionally different:

```text
Local agent:
  terminal · filesystem · repo
  implementation · tests · build · runtime

ChatGPT workspace:
  long-lived context · architecture reasoning
  cross-task reasoning · research · review
  documents · connected project tools
  such as GitHub, Linear, and Google Drive
```

Connected-tool availability depends on the user's ChatGPT workspace and configuration.

GovernLoop connects a **project/reasoning layer** with an **execution layer** instead of trying to turn both sides into identical coding agents.

A key design motivation is to reuse the ChatGPT workspace the user already works in rather than recreating the entire upper layer as a separate API-agent stack.

## What exists today

The long-term idea is a two-agent project loop.

The current stable implementation deliberately starts with a narrower primitive: **a reliable local-agent ↔ ChatGPT checkpoint and review loop.**

As of `v0.1.2`, GovernLoop provides:

- session-level conversation routing;
- five decision-relevant checkpoints;
- evidence attachments with fail-closed delivery;
- Neutral Relay transport over Chrome DevTools Protocol (CDP);
- complete ChatGPT response read-back to the local workflow.

```text
Local Agent
  → GovernLoop Neutral Relay
  → ChatGPT Web over CDP
  → assistant response
  → relay read-back
  → Local Agent continues
```

It is deliberately not a fully autonomous general-purpose orchestration platform.

## Send decisions, not logs

Ordinary progress stays local. Only state that changes the next decision crosses the bridge:

```text
NEW_BLOCKER
UNEXPECTED_STATE
BEFORE_DESTRUCTIVE_ACTION
REVIEW_REQUIRED
FINAL_VERIFICATION
```

**Send decisions, not logs.**

## Evidence is part of the loop

A local path is not evidence delivery. ChatGPT cannot see `/tmp/report.md`.

GovernLoop sends the supporting files themselves as attachments to the same conversation. Before upload, evidence is checked for existence, relevance, secrets, filename, size, and sha256.

If required evidence does not arrive, the checkpoint fails closed instead of reporting a false success.

Full contract: [`docs/architecture/neutral-relay-checkpoint-delivery.md`](docs/architecture/neutral-relay-checkpoint-delivery.md).

## See GovernLoop in action

**This is a real recorded workflow, not a simulated demo.**

```text
Local Agent → GovernLoop → ChatGPT → relay read-back → Local Agent
```

[![GovernLoop live demo — click to watch the full 2-minute workflow](https://github.com/liangzhipengdamon-maker/GovernLoop/releases/download/v0.1.2/demo_poster.png)](https://liangzhipengdamon-maker.github.io/GovernLoop/assets/demo_v0.1.2.mp4)

*Click the image above to watch the full 2-minute recorded workflow.*

## Quick Start

### WorkBuddy

```text
cd <your-project>
/governloop
```

GovernLoop detects the repo/task, creates a session, asks for the ChatGPT conversation URL once, and reuses it for the session.

Optional:

```text
/governloop status
/governloop end
```

### Generic local agents

Claude Code, Codex, OpenCode, scripts, and other local agents can invoke the same session manager directly:

```bash
python3 <repo>/skills/workbuddy/governloop/scripts/governloop_session.py new
python3 <repo>/skills/workbuddy/governloop/scripts/governloop_session.py bind https://chatgpt.com/c/<conversation-id>
python3 <repo>/skills/workbuddy/governloop/scripts/governloop_session.py checkpoint REVIEW_REQUIRED --message "..." --attach <evidence>
python3 <repo>/skills/workbuddy/governloop/scripts/governloop_session.py end
```

Guides: [`QUICK_START`](docs/QUICK_START.md) · [`USAGE`](docs/USAGE.md) · [`AGENT_INTEGRATIONS`](docs/AGENT_INTEGRATIONS.md) · [`MULTI_PROJECT_WORKFLOW`](docs/MULTI_PROJECT_WORKFLOW.md)

## Works with

| Agent | Entry point |
|---|---|
| **WorkBuddy** | `/governloop` |
| **OpenCode** | GovernLoop skill |
| **Claude Code** | session manager CLI |
| **Codex** | session manager CLI |
| **Any local coding agent** | session manager CLI or Neutral Relay |

All integrations share the same model:

```text
repo → task → session → conversation → checkpoints → evidence → end
```

Conversation URLs stay session-level rather than being permanently bound to a project.

## Current stable release

**v0.1.2 — Reliable attachment-message delivery confirmation.**

The key reliability lesson: **clicking Send is not confirmed delivery.** GovernLoop uses state-based confirmation:

```text
draft still present  → one safe retry
composer cleared     → SEND_PENDING — do not resend
new user turn        → DELIVERY_CONFIRMED
```

This protects against duplicate sends when the UI clears before the new turn renders.

See [`CURRENT_STATUS`](docs/ops/CURRENT_STATUS.md) and [`RELEASE_NOTES_v0.1.2`](docs/ops/RELEASE_NOTES_v0.1.2.md).

## Neutral Relay

Canonical implementation:

```text
tools/neutral-relay/neutral_relay.py
```

The target ChatGPT conversation must already be open in a CDP-enabled browser.

A transport run is successful only when the relay writes the **complete assistant response** to the requested local output file. External CDP probes are diagnostic only; they do not substitute for relay read-back.

Low-level usage and CLI details: [`docs/USAGE.md`](docs/USAGE.md).

## What GovernLoop is not

- **Not** an autonomous multi-agent platform, workflow engine, policy engine, or governance authority.
- **Not** a replacement for Codex, Claude Code, OpenCode, or WorkBuddy.
- **Not** an implementation of GitHub / Linear / Google Drive APIs; those are connected-workspace capabilities when available.

## Design principles

- Separate execution context from review/reasoning context.
- Send decisions, not logs.
- Deliver real evidence, not local paths.
- Fail closed when delivery is uncertain.
- Keep human authority at meaningful decision points.

## Documentation

- [`docs/QUICK_START.md`](docs/QUICK_START.md) — 3-command user guide.
- [`docs/USAGE.md`](docs/USAGE.md) — full session-manager and relay reference.
- [`docs/AGENT_INTEGRATIONS.md`](docs/AGENT_INTEGRATIONS.md) — per-agent setup.
- [`docs/MULTI_PROJECT_WORKFLOW.md`](docs/MULTI_PROJECT_WORKFLOW.md) — cross-project workflow.
- [`docs/architecture/neutral-relay-checkpoint-delivery.md`](docs/architecture/neutral-relay-checkpoint-delivery.md) — evidence-delivery contract.

---

**One agent understands the project.  
One agent operates the machine.  
GovernLoop keeps them in the same loop.**

```text
Reasoning + Execution + Evidence + Human Authority
```
