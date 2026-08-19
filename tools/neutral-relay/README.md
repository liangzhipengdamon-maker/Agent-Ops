# Neutral Relay Transport

GovernLoop Neutral Relay is a minimal transport utility that sends a natural-language request to an already-open ChatGPT conversation over Chrome DevTools Protocol (CDP), waits for the correlated Assistant turn to settle, and writes the complete response to a local output file.

## Boundaries

- **Transport only.** The relay does not authorize repository mutation, PR creation, Ready, merge, release, or deployment.
- `REVIEW_REQUEST_ID` is used for request correlation; ordinary transport does not require PR/HEAD/ACK envelopes unless the task itself needs them.
- Diagnostic CDP probes do not substitute for canonical relay success. Canonical success requires relay exit 0 and the relay-written output.

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
    "liangzhipengdamon-maker/GovernLoop": {
      "conversation_url": "https://chatgpt.com/c/...",
      "cdp_port": 9233
    }
  }
}
```

A repository route should point to a ChatGPT conversation selected for that repository and already open in the CDP-enabled browser before real transport.

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
