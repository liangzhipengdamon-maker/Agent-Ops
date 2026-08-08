# AGE-20 Governance Baseline V1

> Canonical baseline of AgentOps current governance capabilities.
> Planning / documentation only. No runtime behavior changes.

## 1. Purpose

This document establishes the single canonical baseline of AgentOps current
governance capabilities.

It is **not** a new feature.
It is **not** an execution system.
It is **not** an automation extension.

It only records the governance capabilities that are already implemented and
validated as of this baseline.

The baseline reflects current `main` after the following completed work:

- **AGE-5** — Action-specific Authorization Verifier
- **AGE-17** — Backlog Reconciliation
- **AGE-18** — Governance Stop Auto-Report Protocol
- **AGE-19** — Neutral Relay Transport Hardening

## 2. Current Architecture State

### 2.1 Authorization Layer

Implemented capabilities:

- **AGE-3 Authorization Design** — authority mapping and mission authorization
  envelope design (`docs/architecture/age-3-authority-and-mission-authorization-design.md`)
- **AGE-5 Action-specific Authorization Verifier** — verifies a proposed
  action against trusted provenance and exact bindings
  (`docs/governance/action_specific_authorization_verifier.md`,
  `scripts/auth_verifier.py`)

Principle:

> **Authorization ≠ Execution**
>
> The verifier confirms that an action is authorized. It does **not**
> automatically grant or execute anything.

### 2.2 Execution Control Layer

Implemented capabilities:

- **Ready / Merge separation** — marking a PR Ready is a distinct gate from
  merging it
- **WAITING_PO_AUTH** — terminal state after review PASS; no further action
  until the Product Owner authorizes
- **STOP_AND_WAIT** — fail-closed terminal state on drift, ambiguity, or
  unauthorized condition

Principle:

> **Review PASS is not execution authorization.**

### 2.3 Communication Layer

Implemented capabilities (AGE-19 / Neutral Relay):

- **Neutral Relay transport** — request/response transport between the local
  Builder and the external GPT Reviewer conversation
- **Strict request correlation** — only the latest assistant response that
  binds all required fields is accepted
- **request_id / repo / PR / HEAD binding** — correlation requires exact match
  of all four identifiers

### 2.4 Runtime Isolation Layer

Implemented capabilities (AGE-19):

- **Dedicated CDP port** — AgentOps uses port `9233` (separate from LearnMind
  `9223`)
- **Dedicated browser profile** — AgentOps uses `~/.agentops/chrome-profile`
- **Conversation identity binding** — exact conversation UUID match; never
  active-tab / first-tab / title-only selection
- **Cross-project isolation** — AgentOps, LearnMind and other projects each
  operate on their own browser runtime, preventing context contamination

## 3. Governance Rules Currently Established

### 3.1 Authority Rules

- **PO authorization is the source of permission** — only explicit Product
  Owner instruction grants authorization.
- **Review is evidence, not authorization** — a PASS verdict does not grant
  Ready, Merge, or Deploy.

### 3.2 Mutation Rules

- **Verify → Mutate → Verify** — every remote mutation is preceded and
  followed by verification against the remote source of truth.

### 3.3 Merge Rules

- **Exact HEAD binding** — a merge must bind the exact reviewed HEAD SHA.
- **Merge requires explicit authorization** — merging requires separate,
  explicit Product Owner authorization.

### 3.4 Failure Rules

- **Fail closed** — any missing, mismatched, or unverifiable condition is
  treated as a denial.
- **STOP_AND_WAIT** — on drift or ambiguity, execution halts and control
  returns to the Product Owner.
- **Unknown state cannot continue** — an ambiguous result stops execution; it
  is never interpreted as approval.

## 4. Current Capabilities Matrix

| Capability | Status | Evidence |
|---|---|---|
| Authorization verification | Complete | AGE-5 (`auth_verifier.py`) |
| Review / evidence separation | Complete | AGE-3 / AGE-5 |
| Ready / Merge gate separation | Complete | AGE-3 design, WAITING_PO_AUTH |
| Stop protocol (auto-report & ACK) | Complete | AGE-18 |
| Neutral Relay transport | Complete | AGE-19 |
| Strict request correlation | Complete | AGE-19 |
| Runtime isolation (CDP/profile) | Complete | AGE-19 E2E |
| Conversation identity binding | Complete | AGE-19 E2E |
| Cross-project isolation | Complete | AGE-19 E2E |
| Backlog reconciliation | Complete | AGE-17 |

## 5. Explicit Non-Goals

As of this baseline, AgentOps is **not**:

- an autonomous developer
- an autonomous merger
- an autonomous deployer
- an unrestricted agent executor
- a production orchestration platform

Each of these would require separate design, authorization, and validation.

## 6. Future Evolution Boundary

This section records **direction only** — it is not a plan and does not start
any implementation.

Future areas **may** include:

- **execution boundary** — defining exactly what a controlled execution step
  may touch
- **controlled runner** — a bounded, one-action-at-a-time execution governor
- **multi-agent coordination** — structured coordination between multiple
  agents under the same governance rules

None of these are started by AGE-20.

## 7. Governance State

> **AGE-20 itself is documentation baseline only.**
>
> - No runtime behavior changes.
> - No authorization changes.
> - No execution changes.
