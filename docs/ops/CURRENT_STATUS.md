# GovernLoop Current Status

Status date: 2026-08-22

## Current repository baseline

- `main`: `84073d8546730c812f4203a15cece03bdedd30d0`
- Merge source: PR #98 — v0.1.2 release docs/version/demo (builds on PR #97 delivery state machine, 79f8c9f)
- Verified tree: delivery state machine (`SEND_DRAFT_STILL_PRESENT` / `SEND_PENDING` / `SEND_PENDING_TIMEOUT` / `DELIVERY_CONFIRMED_PRIMARY` / `DELIVERY_CONFIRMED_AUXILIARY`)
- Neutral Relay: `tools/neutral-relay/neutral_relay.py`

## Verified capability

GovernLoop currently provides a minimal natural-language transport between a local agent and ChatGPT Web through an already-open CDP-enabled browser conversation.

Strict cross-project E2E validation was completed against `liangzhipengdamon-maker/LearnMind-Music-Lab` using PR #74 exact HEAD before merge. The relay itself stayed alive through streaming, exited `0`, created the output artifact, and wrote the complete ChatGPT response. The output matched the visible assistant response.

A subsequent real-project automation workflow also exercised automatic handoff to ChatGPT and return of the review result, providing an additional real-work validation beyond the README smoke test.

PR #77 (Issue #76) resolved the reused-conversation correlation blocker: the relay now confirms the user turn created by the current send and reads the assistant turn that follows it, instead of relying on an assistant-turn count increase. Both clean/new and reused (multiple prior turns) conversation E2Es pass through relay read-back itself.

## Current transport contract

Required request fields:

```text
REVIEW_REQUEST_ID: <unique-id>
REPO: owner/repository

<natural-language task>
```

Response format is ordinary natural language. The transport does not require GPT to echo routing fields or return a structured `PR` / `HEAD` / `ACK` / `RESULT` / `FINAL` envelope.

Completion requires the new assistant turn to stop streaming and its text to stabilize before the relay writes output. The assistant wait timeout is configurable through `--wait-timeout`; the recovery baseline defaults to 900 seconds.

## Out of scope for this baseline

The recovery baseline is not the later complex governance/runtime stack. Historical `start`, `setup-task-scope`, lifecycle authorization, strict reviewer response envelopes, and similar later workflows are not part of the current minimal transport contract.

GovernLoop transport success also does not itself authorize code mutation, PR creation, merge, deployment, or other project actions.

## v0.1.2 — Reliable delivery confirmation (patch)

v0.1.2 is a reliability patch for Neutral Relay message delivery, especially
review/checkpoint messages that carry evidence attachments. It does **not**
change the transport contract or the agent-agnostic positioning; it tightens
delivery confirmation so "send button clicked" is no longer treated as
"message delivered".

Delivery changes (merged via PR #97):

- Strong send confirmation: a send is confirmed only when the composer clears
  **and** the thread's user-turn count increases by one (PRIMARY), or — while
  SEND_PENDING — a guarded new assistant turn appears with no assistant
  streaming before the send (AUXILIARY).
- Three-state model: `SEND_DRAFT_STILL_PRESENT` (composer non-empty → one safe
  re-click), `SEND_PENDING` (composer cleared, thread not yet confirmed →
  never re-click / re-upload / re-inject), `SEND_PENDING_TIMEOUT` (no resend;
  manual verification guidance).
- Duplicate-send protection: a safe re-click is permitted only while the
  original draft is still present; once the composer clears, automatic resend
  is prohibited.
- Configurable `--send-confirm-timeout` (default 30s) and
  `--send-pending-timeout` (default 90s).
- Manual-recovery guidance explicitly forbids re-running the same send path
  after a successful manual send.

Validated on `main` (post-PR #97) with the full suite: relay 35/35,
session-manager 24/24, relay adapter 5/5, worktree status 11/11 (total 75/75).

## Release closure

The current stable release is `v0.1.2` (reliability patch for Neutral Relay
delivery confirmation). Tag `v0.1.2` and the corresponding GitHub Release were
created from the v0.1.2 release commit on `main`.
