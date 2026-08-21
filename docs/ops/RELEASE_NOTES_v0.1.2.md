# GovernLoop v0.1.2

## Summary

v0.1.2 is a reliability patch for Neutral Relay message delivery,
especially review/checkpoint messages carrying evidence attachments.

It does **not** introduce a new architecture or change the transport contract.
It tightens delivery confirmation so that "Send button clicked" is no longer
treated as "message delivered".

## What changed

### Strong delivery confirmation

A Send click alone is no longer treated as delivery success.

Primary confirmation requires both signals:

- composer cleared
- user-turn count increased by exactly one

### SEND_PENDING

If the composer clears before the user turn renders, the relay enters
`SEND_PENDING` rather than immediately declaring failure.

While `SEND_PENDING`:

- no re-click
- no re-upload
- no text re-injection
- wait for canonical user-turn confirmation
- optionally accept a guarded new assistant turn as auxiliary confirmation
  (only when no assistant was streaming before the send)

### Duplicate-send protection

A safe re-click is permitted only while the original draft is still present in
the composer.

Once the composer clears, automatic resend behavior is prohibited.

### Manual recovery

`SEND_NOT_CONFIRMED` and `SEND_PENDING_TIMEOUT` now provide recovery guidance
without instructing the user to re-run the same send path. After a successful
manual send, the guidance explicitly forbids re-running the same request
(duplicate-delivery risk) and suggests recording
`DELIVERY_MODE=MANUAL_SEND_RECOVERY`.

### Failure handling

Unresolved delivery state fails closed:

- `SEND_DRAFT_STILL_PRESENT` → one safe re-click → still non-empty →
  `SEND_NOT_CONFIRMED`
- `SEND_PENDING` → window expires → `SEND_PENDING_TIMEOUT` (no resend)

Attachment delivery behavior is unchanged.

## New configuration

- `--send-confirm-timeout` (default 30s): window to observe composer-clear +
  user-turn +1 before the safe re-click / fail-closed path.
- `--send-pending-timeout` (default 90s): window to observe thread confirmation
  after the composer clears.

## Validation

Re-run on `main` at the v0.1.2 release commit (post PR #97):

- neutral relay tests — 35/35
- send confirmation tests — 10/10 (subset of the above, new in PR #97)
- attachment delivery tests — part of the relay suite
- session-manager tests — 24/24
- relay adapter tests — 5/5
- worktree status tests — 11/11
- **total — 75/75**

`python3 -m py_compile` passes on all changed modules. `README.md` link/path
and CLI `--help` for the new timeout arguments were sanity-checked.

## Compatibility

Agent-agnostic positioning is unchanged: WorkBuddy `/governloop`, OpenCode
skill, Claude Code, Codex, and generic local coding agents all use the same
Neutral Relay transport. No historical runtime/commands were reintroduced.
