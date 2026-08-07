# Neutral Relay Transport

This is a machine-level neutral infrastructure tool designed to securely transport review requests to an external ChatGPT Reviewer session via Chrome DevTools Protocol (CDP), without coupling the business logic of any specific repository (e.g., Agent-Ops, LearnMind-English) to the transport mechanism.

## Boundaries
- **Neutral Relay** ONLY handles transport. It does not parse or evaluate diffs, PR state, verdicts (PASS/FAIL).
- **Builder Agents** CANNOT run local GPT instances to substitute for the independent external Reviewer.
- **Cross-Talk Prevention**: `REVIEW_REQUEST_ID` ensures that a delayed reply from an older request doesn't overwrite a current request's state. Configuration-based routing isolates repositories.

## Installation

This utility is meant to be installed to a machine-level user directory so that multiple projects can share it without interdependent paths:

```bash
mkdir -p ~/.agentops/relay
cp tools/neutral-relay/neutral_relay.py ~/.agentops/relay/
cp tools/neutral-relay/config.example.json ~/.agentops/relay/config.json
```

## Configuration

Edit `~/.agentops/relay/config.json` to map your repository to the corresponding active ChatGPT conversation URL and your local Chrome CDP port.

```json
{
  "routes": {
    "liangzhipengdamon-maker/Agent-Ops": {
      "conversation_url": "https://chatgpt.com/c/...",
      "cdp_port": 9223
    }
  }
}
```

## Usage

```bash
python ~/.agentops/relay/neutral_relay.py \
  --request-file <path_to_request.txt> \
  --output-file <path_to_gpt-review.md> \
  --config-file ~/.agentops/relay/config.json
```

You can use `--dry-run` to verify routing without firing CDP commands.
