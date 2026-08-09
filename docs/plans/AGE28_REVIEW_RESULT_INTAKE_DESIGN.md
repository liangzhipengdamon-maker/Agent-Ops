# AGE-28 — Review Result Intake & Decision Flow Design

> Design for transferring GitHub PR review outcomes into the AgentOps
> long-task decision loop. AGE-24 extension. Planning-only. No
> production implementation.

## 1. Problem Statement

The current gap:

```
Local Agent completes work
        ↓
GitHub PR created
        ↓
GPT Web performs independent review
        ↓
How does Builder Agent receive and act on the review result?
```

The phase-transition / state machinery (AGE-24 Phase 0-4) controls what
happens *after* a decision is known, but there is no controlled flow to
**intake the review result** from GitHub PR and route it back to the
Builder.

## 2. Responsibilities (Builder / Reviewer separation)

| Role | Responsibility | Boundary |
|---|---|---|
| **Local Agent (Builder)** | Reads review outcomes; executes follow-up actions | Must NOT self-approve |
| **GPT Web** | Independent Reviewer; technical + architectural judgment | Stays independent; not replaced |
| **GitHub PR Review** | Review result **source of truth** | Authoritative record |

This document designs the **Builder-side** intake flow. GPT Web's review
behavior is unchanged (independent reviewer). GitHub PR is the canonical
review record.

## 3. Goal Flow

```
GitHub PR Review Event
        ↓
Review Result Intake
        ↓
Risk Judgment Trigger
        ↓
Decision Routing
```

- **Review Result Intake**: read the PR review state from GitHub.
- **Risk Judgment Trigger**: classify the review outcome (PASS /
  CHANGES_REQUESTED / BLOCKED / NEEDS_OWNER_DECISION) and feed it to the
  Phase Policy risk model.
- **Decision Routing**: route to auto-continue, human gate, or
  termination based on the review outcome + phase policy.

## 4. GitHub Review Event Model

### 4.1 Event source

GitHub PR Review is the **source of truth**. The intake reads the
authoritative PR review state via the GitHub API (e.g.
`gh pr view <PR> --json state,reviews,mergeable` or the Reviews API).

### 4.2 Event fields

The intake event model:

```
PR_REVIEW_EVENT
  pr: <PR number>
  repo: <canonical repo>
  head: <exact reviewed HEAD SHA>
  review_state: <APPROVED|CHANGES_REQUESTED|COMMENTED|DISMISSED|PENDING>
  review_decision: <reviewDecision from PR>
  reviewer: <reviewer identity>
  reviewed_at: <ts>
  body: <review text (evidence)>
  review_author_association: <association>
```

### 4.3 Event granularity

- A PR has a **review decision** (APPROVED / CHANGES_REQUESTED /
  REVIEW_REQUIRED / PENDING).
- Individual **reviews** may be COMMENTED (non-blocking) or
  CHANGES_REQUESTED (blocking).
- The intake must bind the event to the **exact PR + exact reviewed HEAD**
  to avoid acting on a stale review.

## 5. Review Result Parsing

### 5.1 Parsed decision

The intake maps GitHub state → an AgentOps decision:

| GitHub state | Parsed decision | Risk class |
|---|---|---|
| `APPROVED` | `PASS` | evidence, not authorization |
| `CHANGES_REQUESTED` | `CHANGES_REQUESTED` | follow-up required |
| `COMMENTED` | `COMMENTED` | non-blocking |
| `DISMISSED` / `PENDING` | `INCOMPLETE` | wait |
| `BLOCKED` (via review text/CI) | `BLOCKED` | stop |

### 5.2 Parsing rules

- **Strict**: the parsed decision must be derived from the GitHub review
  source of truth, not from a narrative copy.
- **Evidence only**: `APPROVED` is evidence that the reviewer approved; it
  does **not** authorize merge / deploy / self-approval.
- **Fail closed**: if the PR state cannot be read or is ambiguous, the
  intake emits `INCOMPLETE` (wait), never a fabricated verdict.

### 5.3 Correlation

The intake binds `repo + PR + HEAD` exactly (matching the AGE-19 relay
correlation contract). A review on a different HEAD is stale and must be
ignored until the reviewed HEAD matches.

## 6. Builder Notification Mechanism

### 6.1 Where the Builder learns of a review

- The Builder polls the PR review state (bounded interval) at the next
  wake / phase boundary.
- A **Review Result Intake record** is written locally
  (`.agent-state/intake/<pr>-<head>.json`) so the Builder can resume
  after an interruption.
- The Builder does **not** rely on conversational context to know the
  review outcome.

### 6.2 Notification event

```
REVIEW_RESULT_READY
  pr: <PR>
  head: <exact HEAD>
  decision: <PASS|CHANGES_REQUESTED|...>
  risk_class: <LOW|MEDIUM|HIGH>
  evidence_ref: <PR review id / gh output>
```

### 6.3 Non-interruption

The review intake is checked at phase boundaries, not mid-phase. This
preserves the "one bounded action per wake" principle.

## 7. LoopX State Update Boundary

### 7.1 What the intake writes to LoopX

On a parsed review result, the Builder updates LoopX:

| LoopX artifact | Update |
|---|---|
| `ACTIVE_GOAL_STATE.md` | record review decision + follow-up todo |
| Todo (follow-up) | add/update the CHANGES_REQUESTED remediation todo |
| History (`refresh-state`) | append a `review_result_intake` record |
| Lease | release the lease when the review resolves; re-acquire for follow-up |

### 7.2 What the intake does NOT write

- The intake does **not** write an authorization record. `APPROVED` is
  evidence, not a grant.
- The intake does **not** auto-transition a phase that requires a human
  gate.

### 7.3 Synchronization

- GitHub PR is the review source of truth.
- LoopX is the durable task-state projection.
- The Builder reconciles both on wake (read PR review → read LoopX → diff
  → act).

## 8. Failure Recovery

| Failure | Detection | Recovery |
|---|---|---|
| PR review not readable (API error) | intake exception | retry bounded; if persists → `INCOMPLETE` (wait), never fabricate |
| HEAD mismatch (review on stale HEAD) | correlation check | ignore until HEAD matches; log drift |
| Builder process interrupted mid-intake | no intake record written | on wake, re-read PR review from GitHub (source of truth), re-write record |
| LoopX write fails | refresh-state error | keep GitHub as truth; retry LoopX write; surface blocker |
| Ambiguous review text | parse fail-closed | emit `INCOMPLETE` (wait) with the raw evidence |

## 9. Governance Boundaries

- **No self-approval**: the Builder reads reviews but never self-approves.
- **No bypass of AgentOps authorization**: merge / deploy still require
  the PO / Phase Policy gate.
- **GPT Web stays independent**: this design does not replace GPT Web
  review; it only routes the GitHub record.
- **Evidence not authorization**: `APPROVED` and `PASS` are evidence.
- **Fail closed**: unknown / ambiguous review state halts, never invents.
- **Exact binding**: repo + PR + HEAD must match before any decision is
  acted on.

## 10. Validation Target (future)

The future validation flow (mirroring AGE-26 sandbox style):

```
GitHub PR Created
        ↓
GPT Web reviews PR (independent)
        ↓
Intake reads PR review (source of truth)
        ↓
Risk Judgment Trigger (Phase Policy)
        ↓
Decision Routing:
   PASS (low-risk)         -> AUTO_CONTINUE
   CHANGES_REQUESTED       -> follow-up todo
   BLOCKED / HIGH_RISK     -> WAITING_HUMAN_GATE
        ↓
LoopX state preserved
```

## 11. Boundary

- Design only.
- No production implementation.
- No replacement of GPT Web review.
- No bypass of AgentOps authorization.
- No merge, no deploy.
- Builder designs Builder-side flow; GPT Web remains Independent Reviewer.
- Local Execution Agent role only.
