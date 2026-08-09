# AGE-29 — Canonical Risk Judgment Policy Design

> Governance rules that decide whether a completed task can continue
> automatically, requires GPT Web decision, or requires PO authorization.
> AGE-24 / AGE-28 extension. Design only. No runtime implementation.

## 1. Problem Statement

```
GitHub Review PASS
        ↓
Can execution continue?
        ↓
Who decides?
```

A review PASS is evidence that the reviewer approved the work. It does
**not** answer "can execution continue" — that is a **risk judgment**
question answered by a canonical policy, not by the review itself.

## 2. Risk Classification Model

```
LOW RISK
    ↓
Automatic continuation  (or GPT decision for optional improvements)

MEDIUM RISK
    ↓
GPT Web judgment required

HIGH RISK
    ↓
WAITING_PO_AUTH
```

## 3. Risk Matrix

Each risk factor is scored and the highest applicable risk class wins
(max risk wins).

| # | Risk factor | LOW | MEDIUM | HIGH |
|---|---|---|---|---|
| 1 | Production code changes | no | contained / isolated | core / broad |
| 2 | Security boundary changes | none | auth-adjacent | auth / secrets / trust boundary |
| 3 | Authorization changes | none | policy doc / evidence only | verifier / grant rules |
| 4 | Database / schema changes | none | isolated / reversible | migration / production schema |
| 5 | Deployment actions | none | preview / sandbox | production deploy |
| 6 | Merge actions | none | Draft / low-traffic | merge to main / protected branch |
| 7 | Protected path changes | none | adjacent | inside protected path |
| 8 | Irreversible operations | none | reversible with evidence | irreversible / destructive |
| 9 | Scope deviation | none | minor / documented | material scope expansion |
| 10 | Unknown system impact | none | partially known | unknown / unexplored |

### 3.2 Risk score rule

- Every factor starts at LOW.
- A factor rises to MEDIUM if the change touches its medium column.
- A factor rises to HIGH if the change touches its high column.
- **Overall class = highest class across all factors.**
- If any factor is HIGH → the whole task is HIGH (WAITING_PO_AUTH).

## 4. Decision Rules

### 4.1 LOW risk

- Execution may continue **automatically** through the Phase Policy
  auto-continue path (Transition Controller).
- GPT Web may still be consulted for optional improvements, but a GPT
  decision is **not** mandatory.
- No PO authorization required.

### 4.2 MEDIUM risk

- Execution may **not** continue automatically.
- A **GPT Web decision** is mandatory: the Reviewer evaluates the change
  and returns `PASS` / `CHANGES_REQUESTED` / `BLOCKED` /
  `NEEDS_OWNER_DECISION`.
- The Builder waits for the GPT Web verdict before proceeding.
- PO authorization is not required if GPT Web returns PASS and the
  change remains MEDIUM.

### 4.3 HIGH risk

- Execution **halts** at `WAITING_PO_AUTH`.
- Neither automatic continuation nor GPT Web decision is sufficient.
- **PO authorization is mandatory and final**.
- The Builder stops and returns control to the PO.

## 5. Escalation Rules

| Current class | Trigger | Escalate to |
|---|---|---|
| LOW | a factor is reclassified to MEDIUM | MEDIUM |
| LOW | a factor is reclassified to HIGH | HIGH |
| MEDIUM | a factor is reclassified to HIGH | HIGH |
| MEDIUM | GPT Web verdict is `BLOCKED` | HIGH (WAITING_PO_AUTH) |
| MEDIUM | GPT Web verdict is `NEEDS_OWNER_DECISION` | HIGH (WAITING_PO_AUTH) |
| HIGH | any HIGH factor present | stays HIGH (final) |

Escalation is **one-way upward** for a given task. De-escalation requires
a fresh re-evaluation of a **new** task state with new evidence.

## 6. Human Gate Conditions

A human gate (WAITING_PO_AUTH) is triggered when:

1. The overall risk class is HIGH.
2. A MEDIUM task's GPT Web verdict is `BLOCKED` or
   `NEEDS_OWNER_DECISION`.
3. The task requires a merge, production deploy, auth change, database
   migration, or protected-path change.
4. The task exceeds its retry limit.
5. The task produces an irreversible operation with no evidence of
   reversibility.

## 7. Auto-Continue Conditions

Automatic continuation is allowed **only** when:

1. Overall risk class is LOW.
2. No HIGH factor present.
3. Phase Policy auto-continue is enabled for the next phase.
4. No retry limit exceeded.
5. GPT Web (if consulted) returned `PASS` (not BLOCKED).

## 8. Who Decides (responsibility)

| Class | Decider | Authority |
|---|---|---|
| LOW | Phase Policy / Transition Controller | auto-continue |
| MEDIUM | GPT Web (Independent Reviewer) | verdict required |
| HIGH | PO | authorization final |

- The Builder never decides risk class for itself at HIGH.
- GPT Web never authorizes merge / deploy (it decides MEDIUM risk only).
- PO is the final authority for HIGH risk.

## 9. Governance Boundaries

- **No automatic permission escalation**: a LOW task never silently
  becomes a deploy authorization.
- **PO authority remains final for high-risk actions**: merge, deploy,
  auth, DB, protected path, irreversible ops.
- **Evidence not authorization**: `APPROVED` / `PASS` is evidence only.
- **Fail closed**: unknown / ambiguous risk → classify as HIGH
  (WAITING_PO_AUTH), never default to LOW.
- **Exact binding**: any decision is bound to the exact task + PR + HEAD.

## 10. Validation Target (future)

```
Task completed -> Risk Judgment (Risk Matrix)
        ↓
LOW      -> Auto Continue (Transition Controller)
MEDIUM   -> GPT Web verdict -> PASS -> continue / BLOCKED -> WAITING_PO_AUTH
HIGH     -> WAITING_PO_AUTH (PO final)
```

## 11. Boundary

- Design only.
- No runtime implementation.
- No automatic permission escalation.
- PO authority remains final for high-risk actions.
- No merge, no deploy.
- Local Execution Agent role only; GPT Web remains Independent Reviewer.
