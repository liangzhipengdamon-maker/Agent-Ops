# AGE-6 Controlled Execution Boundary Plan

> Planning document for the controlled execution boundary between
> Authorization and Execution in AgentOps.
> Planning / documentation only. No runtime implementation.

## 1. Purpose

This document defines the boundary between **Authorization** and
**Execution** in AgentOps.

It records:

- the **current boundary** between Authorization and Execution
- a **design** for the future execution model (not implemented by AGE-6)
- the **capability boundary** that any future execution layer must respect
- the **fail-closed rules** inherited from existing governance
- the **explicit non-goals** for AGE-6

The core principle is repeated throughout:

> **Authorization ≠ Execution**
>
> The existence of an authorization verifier does not, by itself,
> authorize execution. Execution requires its own dedicated gate.

## 2. Current Boundary

The current AgentOps architecture (see `docs/governance/AGE-20_GOVERNANCE_BASELINE_V1.md`)
defines four roles:

| Role | Responsibility |
|---|---|
| **PO (Product Owner)** | The sole source of authorization. Grants and revokes permissions explicitly. |
| **Reviewer** | Provides independent verification. Produces evidence, not authorization. |
| **Builder** | Performs implementation. Never self-authorizes; never merges; never deploys. |
| **Relay** | Transport only. Carries request/response between Builder and external Reviewer. |

The boundary is therefore:

- **PO → Authorization authority** (explicit instruction is the only source)
- **Reviewer → Independent verification** (verdict is evidence, not authority)
- **Builder → Implementation** (writes code under explicit authorization)
- **Relay → Transport only** (no interpretation, no judgment)

Nothing in the current runtime executes a Builder action autonomously.

## 3. Execution Model Design (future)

The future design — **not implemented by AGE-6** — separates Authorization
from Execution with a dedicated boundary:

```
            Authorization
                  │
                  ▼
       ┌──────────────────────┐
       │  Execution Boundary  │
       │  (planned, AGE-6)    │
       └──────────────────────┘
                  │
                  ▼
                Runner
```

Roles:

- **Authorization** — supplies an authoritative, exact-binding proof that a
  bounded action may proceed.
- **Execution Boundary** — the single gate that validates the Authorization
  against the action's required scope, actor, and allowed mutation, and only
  then permits one bounded step.
- **Runner** — performs exactly one permitted step and reports the outcome.
  It never infers the next step; it never chains authorizations.

AGE-6 records this design. **It does not implement any of these three
layers.**

## 4. Capability Boundary

Any future execution layer must respect the following capability matrix:

| Action | Actor | Required Authorization | Allowed Mutation |
|---|---|---|---|
| Read repository state | Runner (future) | Read-scope authorization bound to exact base SHA | None |
| Run local tests | Runner (future) | Test-scope authorization bound to exact HEAD SHA | None (write only under temp test path) |
| Open PR | Runner (future) | Open-PR authorization bound to exact HEAD SHA, target repo, exact base SHA | Creates Draft PR only |
| Mark PR Ready | Runner (future) | Ready authorization bound to exact reviewed PR number and exact HEAD SHA | Flips Draft → Ready only |
| Merge PR | Runner (future) **never** | Product Owner explicit instruction, exact reviewed PR number, exact reviewed HEAD SHA | Performs the merge |
| Deploy | Runner (future) **never** | Product Owner explicit instruction | Performs the deploy |

Rules that apply to every row:

- The actor and required authorization are bound to an exact identifier (HEAD
  SHA, PR number, repo).
- Mutation is the minimum required to perform the action and nothing more.
- Steps are one-at-a-time. Multi-step chains are not part of a single
  authorization.

## 5. Fail Closed Rules

The execution layer must inherit and never weaken the following rules from
existing governance:

- **Exact binding** — every authorization must bind to an exact identifier
  (no substring, no prefix, no fuzzy match).
- **Scope validation** — the action's required scope must exactly match the
  authorization's granted scope. Any broader action is denied.
- **STOP_AND_WAIT** — on any drift, ambiguity, or unverifiable condition, the
  execution layer halts and returns control to the Product Owner. It never
  interprets an unknown state as permission to continue.
- **Verify → Mutate → Verify** — every mutation is preceded and followed by a
  verification against the remote source of truth.

## 6. Non Goals

AGE-6 itself does **not** include:

- autonomous execution of any kind
- a daemon or background service
- a scheduler or timer-driven trigger
- deployment automation
- any production code change
- any runtime, Neutral Relay, auth verifier, or CI change
- an implementation of the Runner or Execution Boundary

AGE-6 is a planning record only.

## 7. Relationship with Existing AGE

AGE-6 fits the governance baseline as follows:

- **AGE-5** — Action-specific Authorization Verifier — provides the
  *authorization* that any future execution layer must verify before acting.
- **AGE-18** — Governance Stop Auto-Report Protocol — defines the *stop and
  report* behavior any future execution layer must obey.
- **AGE-19** — Neutral Relay Transport Isolation — isolates the *transport*
  used by the Builder and the Reviewer, independent of any execution layer.
- **AGE-20** — Governance Baseline — records the *current* state; AGE-6 is a
  design for the *next* layer and does not modify the baseline.

AGE-6 only **designs** the Execution Boundary. It does not build it.