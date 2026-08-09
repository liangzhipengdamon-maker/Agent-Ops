# Governance Status Reporting & Persistent Wait Protocol

> Current semantics for AGE-18 reporting. This document supersedes the legacy interpretation that every reportable governance state terminates the Controller.

## Objective

Ensure the controlling GPT/PO context receives exact, correlated state evidence without turning a checkpoint or waiting state into task termination.

## Core rule

**Builder STOP != Controller STOP.**

`WAITING_PO_AUTH`, `CHANGES_REQUESTED`, `BLOCKED`, and `NEEDS_OWNER_DECISION` are control states that may pause Builder execution, but they do **not** by themselves terminate the Controller/Watcher.

A report ACK closes the **report-delivery episode only**. It never authorizes a follow-on action and never terminates the control loop by itself.

## State behavior

### CHANGES_REQUESTED / NOT_PASS

Normal remediation transition:

```text
GPT Review
→ current-HEAD remediation
→ Builder consumes findings
→ fix/test
→ new code HEAD
→ GPT Review again
```

Do not route `CHANGES_REQUESTED` through a stop-and-die protocol.

### WAITING_PO_AUTH

Persistent waiting state:

```text
enter WAITING_PO_AUTH
→ Builder may idle/exit
→ Controller/Watcher remains alive
→ notify GPT/PO with exact state
→ observe GitHub + Linear
→ on meaningful change, re-run Review/Risk/Transition
→ continue / ask GPT / remain waiting for PO
```

### BLOCKED / NEEDS_OWNER_DECISION

Pause the relevant execution path and surface the blocker/decision requirement, but keep the control runtime alive unless the task is explicitly closed/cancelled.

## status_report contract

The generated `status_report` must use the exact envelope:

```text
REVIEW_REQUEST_ID: <new UUID>
REPO: <exact repo>
PR: <exact PR>
HEAD: <exact bound HEAD>
REQUEST: status_report
STATE: <state>
SUMMARY: <concise factual summary>
UNAUTHORIZED_ACTIONS: NONE|<explicit list>
```

AGE-18 v1 remains PR-bound for this exact report contract.

## ACK contract

The GPT Reviewer responds with exactly:

```text
REVIEW_REQUEST_ID: <same UUID>
REPO: <exact repo>
PR: <exact PR>
HEAD: <exact bound HEAD>
ACK: status_report_received
```

The ACK is transport/read-back evidence only.

## Delivery semantics

A report is `DELIVERED` only when the configured transport/read-back contract confirms it.

If delivery cannot be confirmed:

1. record `DELIVERY_FAILED` (or the equivalent explicit failure state/evidence);
2. do **not** write a success timestamp/ACK flag;
3. preserve retry/reconciliation evidence;
4. retry only with bounded policy and duplicate protection;
5. do not fabricate success and do not blindly spam duplicate reports.

## Invariants

- Report/ACK/read-back are evidence, never authorization.
- Correlation binds exact request ID, repo, PR, and HEAD.
- Stale/mismatched correlation is rejected.
- No completion/report document may substitute for an implementation acceptance criterion.
- A new report is generated only for a meaningful new episode/state/evidence change.
- The Controller ends only on an explicitly terminal task outcome/policy decision, not merely because the Builder exited or a report was acknowledged.
