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

Before real transport, confirm the target ChatGPT conversation. Do not guess or silently reuse a conversation URL that the user has not selected or previously authorized for this task. If no target conversation is already explicitly established, ask the user for the ChatGPT conversation URL before sending.

For real transport, invoke the canonical relay with the request, output, config, and wait timeout. Read the output only after the relay exits successfully.

Transport success requires all of the following: relay exit code 0; stdout contains `Success: Wrote response to ...`; the relay created the output file; and the output contains the complete assistant response. External CDP probes are diagnostic only and do not substitute for relay read-back.

If relay transport fails, report the real failure point instead of bypassing the relay and presenting probe-read content as a successful GovernLoop result.

This Minimal Transport Recovery baseline does not include the historical `governloop start`, `governloop doctor`, `setup-task-scope`, host-confirm, or lifecycle-authority workflows. Do not call those as part of this skill.

The Neutral Relay is transport only. It does not itself authorize repository mutation, PR creation, merge, release, or deployment.

## Shared agent safety contract

Before performing repository or lifecycle actions, read and follow `docs/ops/AGENT_SAFETY_CONTRACT.md` and the repository-level `AGENTS.md`.

In particular, implementation, commit/push, PR creation, Ready, merge, and deploy/release are separate authorization stages. Never infer a later-stage authorization from PASS, relay success, test success, mergeability, Ready state, task completion, or an earlier-stage authorization.

For Ready, merge, deploy, or release, verify the current remote target and exact HEAD where applicable, then require explicit user authorization for that stage. If the next-stage authorization is absent, STOP and report the current state rather than continuing automatically.
