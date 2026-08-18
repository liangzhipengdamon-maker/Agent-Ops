# GovernLoop

GovernLoop is a lightweight local-agent ↔ ChatGPT transport layer for real project work.

The current stable baseline focuses on one capability: a local agent sends a natural-language request through the Neutral Relay to an already-open ChatGPT conversation over Chrome DevTools Protocol (CDP), waits for the assistant turn to finish streaming, and writes the complete response to a local output file.

## Current status

**Minimal Transport Recovery — cross-project E2E verified.**

The recovery baseline was merged by PR #74. Its Neutral Relay has been verified end-to-end against a separate real repository and in a subsequent real-project automation workflow.

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

## Neutral Relay

Canonical implementation:

```text
tools/neutral-relay/neutral_relay.py
```

CLI:

```bash
python tools/neutral-relay/neutral_relay.py \
  --request-file request.txt \
  --output-file output.md \
  --config-file config.json \
  --wait-timeout 900
```

Required request routing fields:

```text
REVIEW_REQUEST_ID: <unique-id>
REPO: owner/repository

<ordinary natural-language task>
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

## Release line

- `v0.1.0` — original public release.
- `v0.1.1` — planned Minimal Transport Recovery release; cross-project natural-language relay behavior verified before release.

See `docs/ops/CURRENT_STATUS.md` and `docs/ops/RELEASE_NOTES_v0.1.1.md` for the release closure record.
