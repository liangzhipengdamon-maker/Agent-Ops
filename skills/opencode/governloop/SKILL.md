---
name: governloop
description: Use GovernLoop Neutral Relay to send natural-language project context and requests from a local agent to an open ChatGPT Web conversation over CDP, then read the relay-written response.
---

# GovernLoop OpenCode Skill

Use this skill when work should be handed from a local agent to ChatGPT through the GovernLoop Neutral Relay.

Canonical relay: `tools/neutral-relay/neutral_relay.py`.

Current relay arguments: `--request-file`, `--output-file`, `--config-file`, `--wait-timeout` (default 900), and `--dry-run`.

A request contains `REVIEW_REQUEST_ID`, `REPO`, and the ordinary natural-language task. Do not add or require `PR`, `HEAD`, `ACK`, `RESULT`, or `FINAL` unless the user's task explicitly needs them.

Configure the target repository route with an already-open ChatGPT `conversation_url` and its CDP port. A routing dry run may be used before real transport.

For real transport, invoke the canonical relay with the request, output, config, and wait timeout. Read the output only after the relay exits successfully.

Transport success requires all of the following: relay exit code 0; stdout contains `Success: Wrote response to ...`; the relay created the output file; and the output contains the complete assistant response. External CDP probes are diagnostic only and do not substitute for relay read-back.

If relay transport fails, report the real failure point instead of bypassing the relay and presenting probe-read content as a successful GovernLoop result.

This Minimal Transport Recovery baseline does not include the historical `governloop start`, `governloop doctor`, `setup-task-scope`, host-confirm, or lifecycle-authority workflows. Do not call those as part of this skill.

The Neutral Relay is transport only. It does not itself authorize repository mutation, PR creation, merge, release, or deployment.

## Role boundaries

- Human Product Owner grants lifecycle authorization; GPT Reviewer only reviews and gives verdicts; GovernLoop enforces scope and gates; Local Agent executes only within authorized scope.
- GPT Reviewer approval MUST NOT be treated as Human Product Owner authorization.
