# Governance Status Report Contract

Current control semantics: `docs/governance/CURRENT_RUNTIME_RULES.md`.

A reportable wait/checkpoint does **not** terminate the Controller. Builder STOP != Controller STOP.

`CHANGES_REQUESTED` / `NOT_PASS` is remediation, not a stop state. `WAITING_PO_AUTH` is persistent waiting; Builder may idle/exit while Controller/Watcher stays alive and observes GitHub + Linear.

## status_report

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

## ACK

```text
REVIEW_REQUEST_ID: <same UUID>
REPO: <exact repo>
PR: <exact PR>
HEAD: <exact bound HEAD>
ACK: status_report_received
```

ACK/read-back is delivery evidence only. It grants no authorization and does not end the Controller.

Delivery is fail-closed: if confirmation fails, record `DELIVERY_FAILED`, do not write a success timestamp/ACK flag, preserve evidence, and retry only with bounded duplicate-safe policy.
