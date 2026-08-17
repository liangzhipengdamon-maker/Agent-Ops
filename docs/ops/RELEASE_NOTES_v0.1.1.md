# GovernLoop v0.1.1 — Minimal Transport Recovery

## Summary

v0.1.1 restores GovernLoop to a small, verified transport core for local-agent ↔ ChatGPT collaboration.

The release is centered on the Neutral Relay and ordinary natural-language responses. It intentionally does not restore the later complex governance/runtime stack that had become coupled to the transport path.

## What is verified

The recovery baseline was validated in a separate real repository before being merged through PR #74.

Verified path:

```text
Local Agent
  → Neutral Relay
  → ChatGPT Web over CDP
  → complete natural-language response
  → relay read-back
  → relay-created output file
```

The strict E2E evidence required the relay process itself to exit successfully and write the complete assistant response; independent CDP probes were diagnostic only and were not accepted as substitutes for relay read-back.

The recovered path was subsequently exercised in another real-project automation workflow, providing additional evidence that the relay can support substantive agent ↔ GPT handoff rather than only a README smoke test.

## Transport changes since v0.1.0

- Modernized ChatGPT completion detection; no dependency on the historical `Reply actions` / `回复操作` marker.
- Identifies the assistant turn created by the current send instead of dumping the full conversation text.
- Does not require GPT to echo `REVIEW_REQUEST_ID` in a normal natural-language response.
- Treats active streaming as incomplete and never writes a temporarily stable streaming prefix.
- Makes assistant wait timeout configurable with `--wait-timeout`.
- Uses a 900-second default wait window to tolerate observed long ChatGPT generation stalls.

## Current request contract

The relay requires two routing fields:

```text
REVIEW_REQUEST_ID: <unique-id>
REPO: owner/repository
```

The remainder of the request is ordinary natural language.

The response is ordinary natural language. Structured review fields such as `PR`, `HEAD`, `ACK`, `RESULT`, and `FINAL` are not transport requirements.

## Compatibility note

The v0.1.1 recovery line is deliberately narrower than the later unreleased governance/runtime work that existed on `main` before PR #74.

Do not assume historical commands such as `governloop start`, `setup-task-scope`, host confirmation flows, strict reviewer envelopes, or lifecycle authorization gates are part of this release unless separately reintroduced and verified in a future version.

## OpenCode

A minimal OpenCode skill is intended to ship with this release so OpenCode can discover the current Neutral Relay workflow without relying on stale commands from the earlier runtime stack.

## Release gate

Before tagging v0.1.1:

1. Merge the release-closure documentation/skill PR.
2. Verify the resulting `main` still contains the exact Neutral Relay implementation already E2E validated.
3. Run one short release-candidate transport smoke from a clean conversation.
4. Only then create the `v0.1.1` tag and GitHub Release.
