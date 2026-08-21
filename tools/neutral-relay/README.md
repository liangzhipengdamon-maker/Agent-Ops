# Neutral Relay Transport

GovernLoop Neutral Relay is a minimal transport utility that sends a natural-language request to an already-open ChatGPT conversation over Chrome DevTools Protocol (CDP), waits for the correlated Assistant turn to settle, and writes the complete response to a local output file. It also uploads evidence attachments to the same conversation before sending.

Canonical capability contract: `docs/architecture/neutral-relay-checkpoint-delivery.md`.

## Boundaries

- **Transport only.** The relay does not authorize repository mutation, PR creation, Ready, merge, release, or deployment.
- `REVIEW_REQUEST_ID` is used for request correlation; ordinary transport does not require PR/HEAD/ACK envelopes unless the task itself needs them.
- Diagnostic CDP probes do not substitute for canonical relay success. Canonical success requires relay exit 0 and the relay-written output.
- Checkpoint evidence delivery: a local path written in the text is NOT delivery — evidence must be attached (see below).

## Canonical executable

Use the repository copy directly:

```text
tools/neutral-relay/neutral_relay.py
```

Do not install or maintain a second executable copy under `~/.agentops/relay/`.

## Configuration

The canonical default routing config is:

```text
~/.governloop/relay/config.json
```

Example:

```json
{
  "routes": {
    "owner/repository": {
      "conversation_url": "https://chatgpt.com/c/...",
      "cdp_port": 9233
    }
  }
}
```

A repository route should point to a ChatGPT conversation selected for that repository and already open in the CDP-enabled browser before real transport.

## Session routing

- A conversation URL is **task/session-level state**, not permanent project config.
- Ask the user **once per session**; every later checkpoint in the same session reuses the same URL — no repeated asking, nothing written back to config.
- Session-level overrides: `--conversation-url` / `--cdp-port` (never persisted).
- Forbidden: permanent binding, auto-reuse of a previous session, auto-picking the most recent conversation, using another project's conversation, binding to whatever browser tab is open.
- At session end, temporary routing state is removed; the canonical config keeps no conversation binding.

## Review checkpoints

The following checkpoints MUST be reported through GovernLoop (text + evidence attachments to the same bound conversation): `NEW_BLOCKER`, `UNEXPECTED_STATE`, `BEFORE_DESTRUCTIVE_ACTION`, `REVIEW_REQUIRED`, `FINAL_VERIFICATION`. Ordinary progress must not spam the conversation.

Evidence attachment safety (before each file): exists -> relevant -> secret scan -> record filename/size/sha256. Never attach `.env`, tokens, credential backups, browser profiles, caches, `node_modules`, secret-bearing config, irrelevant raw logs. Secret-bearing evidence is only ever attached as a redacted copy (`.redacted`).

## Usage

From the GovernLoop repository root:

```bash
python3 tools/neutral-relay/neutral_relay.py \
  --request-file <path_to_request.txt> \
  --output-file <path_to_response.txt>
```

The relay now uses `~/.governloop/relay/config.json` by default. You can still override the routing authority explicitly when needed:

```bash
python3 tools/neutral-relay/neutral_relay.py \
  --request-file <path_to_request.txt> \
  --output-file <path_to_response.txt> \
  --config-file <alternate_config.json>
```

Use `--dry-run` to verify routing without sending anything through CDP.

### Checkpoint delivery with evidence attachments (session-level target)

```bash
python3 tools/neutral-relay/neutral_relay.py \
  --request-file request.txt \
  --output-file response.md \
  --conversation-url <session-url> \
  --attachment report.md \
  --attachment manifest.json
```

`--attachment` is repeatable. Each file is uploaded through the conversation's file input via CDP `DOM.setFileInputFiles`; the relay verifies the file name becomes visible in the composer before proceeding. Any attachment failure (missing file, no file input, upload error, not visible) is fail-closed: the run aborts with a non-zero exit before the request text is sent, and no response is written — i.e. never a false COMPLETE.

## Tests

```bash
python3 -m unittest tools/neutral-relay/tests/test_neutral_relay.py tools/neutral-relay/tests/test_attachment_delivery.py
```
