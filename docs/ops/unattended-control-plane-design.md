# Controlled Long-Running Runtime Design — AgentOps

> Current operational design. This file supersedes the legacy “one action per wake then suspend” unattended-control-plane model.

## 1. Purpose

AgentOps keeps a governed software task alive across multiple implementation phases, review rounds, Builder exits, and waiting periods without turning every checkpoint into a stop.

The runtime is agent-neutral. The local coding agent may be OpenCode, Antigravity, Claude Code, Codex, or another compatible Builder.

## 2. Core components

```text
Product Owner
   ↓ protected-action authorization
ChatGPT Web
   ↕ review / architecture / medium-risk decisions
Neutral Relay
   ↕ transport only
Controller / Watcher
   ↕ state observation + Review/Risk/Transition
Builder
   ↕ implementation
LoopX / runtime state
```

Repository/task sources:

- GitHub main: code, governance, reviews, technical evidence.
- Linear: active task instructions, acceptance criteria, status, dependencies.

Neither Linear nor runtime state grants authorization.

## 3. Two loops

### Cognitive / execution loop

```text
Builder → GitHub evidence → GPT Review → remediation/decision → Builder
```

### Runtime continuity loop

```text
state → claim/execute → checkpoint → persist → watch/recover/handoff → continue
```

The Controller joins these loops at phase/review/risk boundaries.

## 4. Long-task rule

A wake is **not** limited to exactly one file edit or one low-level action.

Within an active authorized task/scope, the Builder should continue through the bounded implementation needed to reach the next meaningful review/risk checkpoint.

Examples of ordinary continuous execution:

```text
edit → test → fix → test → commit → push → update draft PR
```

A phase completion report is a checkpoint, not a termination condition.

The legacy universal `one-action-per-wake` constraint is historical and non-controlling.

## 5. Review transition

```text
current code HEAD
→ GPT Review
→ CHANGES_REQUESTED/NOT_PASS
→ exact current-HEAD remediation reaches Builder
→ Builder fixes
→ new code HEAD
→ review again
```

The system must propagate the actual remediation body, not merely a boolean that “GitHub changed.”

Review PASS then enters canonical risk routing; it does not automatically enter PO wait.

## 6. Risk transition

Use the canonical risk policy only:

```text
LOW    → AUTO_CONTINUE
MEDIUM → GPT_DECISION_REQUIRED
HIGH   → WAITING_PO_AUTH
```

No watcher/adapter may maintain an independent competing risk classifier.

## 7. Persistent wait

`WAITING_PO_AUTH` is a Controller state, not Controller death.

```text
HIGH
→ notify GPT/PO
→ Builder may idle/exit
→ Watcher remains alive
→ poll/reconcile GitHub + Linear
→ meaningful change
→ Review/Risk/Transition
```

`CHANGES_REQUESTED`, `BLOCKED`, and `NEEDS_OWNER_DECISION` likewise do not imply automatic Controller termination.

## 8. Delivery

Relay delivery is fail-closed.

Confirmed ACK/read-back → delivered evidence.

Unconfirmed → explicit `DELIVERY_FAILED`, no false success timestamp, bounded retry/reconciliation, duplicate protection.

Transport success and report ACK are evidence only and never authorization.

## 9. Authorization

An active implementation authorization covers ordinary work inside the task/base/scope. It does not require the final future HEAD before implementation creates it.

Protected actions still require explicit PO authorization, including Ready, Merge, Deploy/production access, force push/main rewrite, authorization-policy changes, and other canonical HIGH actions.

Exact HEAD binding applies when a protected action acts on an already-existing commit.

## 10. Completion

For a code task, the live remote HEAD must contain the actual code fix. A docs-only report commit cannot satisfy a runtime/code acceptance criterion.

The Controller ends only on an explicitly terminal task outcome, not on phase completion, Builder exit, waiting state, review remediation, or report ACK.
