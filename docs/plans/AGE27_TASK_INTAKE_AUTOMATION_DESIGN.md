# AGE-27 — Task Intake Automation Design

> Design for the automation layer between Linear task creation and Local
> Agent execution. AGE-24 extension. Planning-only. No production code,
> no deployment, no GPT Relay replacement.

## 1. Current Manual Bottleneck Analysis

### 1.1 The remaining manual step

Today the workflow is:

```
Human / GPT creates Linear Issue
        ↓
Manual copy prompt
        ↓
Local Agent starts
```

The manual copy step is the last human intervention in the loop. After
it, AGE-24 Phase 0-4 proved the pipeline can continue automatically
(Transition Controller, Phase Policy, LoopX state, AgentOps governance).

### 1.2 Observed evidence (AGE-21 → AGE-26)

- **AGE-21/22**: the Local Agent executed, produced artifacts, ran CI,
  sent the review request, and stopped at WAITING_PO_AUTH. But the task
  was *started* by a human/GPT prompt copied into the session.
- **AGE-24 Phase 0-4**: phase transitions, LoopX state, and governance
  are validated. The gap is the **ingress**: no agent wakes up when a
  new Linear issue is created.
- **AGE-26 (Phase 5A)**: requires "Linear Issue Created → Local Agent
  Claims Task" as the first step of the sandbox validation — but there
  is no automated watcher to drive that first step.

### 1.3 The bottleneck in one sentence

The system can control what happens *after* a task starts, but nothing
starts a task when Linear changes.

## 2. Task Intake Component Design

### 2.1 Responsibilities

A **Task Intake Worker** is a bounded, read-only watcher that:

1. Monitors Linear for new/updated issues in the authorized project.
2. Detects issues that are eligible for Local Agent execution.
3. Emits a **Task Discovered** notification to the Master Agent.
4. Does **not** execute, decide, or mutate.

It is deliberately minimal: discover + notify only.

### 2.2 Non-responsibilities (Agent Boundary)

The Task Intake Worker must **not**:

- make architecture decisions,
- execute coding tasks,
- claim/lease tasks itself,
- bypass approval rules,
- modify Linear,
- modify the GPT Relay,
- start autonomous execution without AgentOps policy checks.

### 2.3 Component structure

```
[Linear] ──(poll/event)──▶ [Task Intake Worker] ──▶ [Master Agent Notification]
                                                         │
                                                         ▼
                                                   [LoopX State Init]
                                                         │
                                                         ▼
                                                   [Execution (Agent)]
```

The Worker is stateless per scan. It produces a **Task Discovered event**
and nothing else.

## 3. Linear Integration Approach

### 3.1 Polling vs event-driven

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| Polling (e.g. Linear GraphQL every N seconds) | simple, deterministic, no infra | latency up to N seconds; must handle rate limits | **Recommended default** (bounded interval, e.g. 60s) |
| Event-driven webhook | near-real-time | needs a hosted endpoint (conflicts with "no daemon/web service" constraint) | Defer; note as future |

Because the AGE-24 constraints forbid a daemon/web service, the
**bounded polling worker** (a CLI step run by the Master Agent or a
scheduled tick) is the pragmatic choice.

### 3.2 Eligibility criteria

An issue is eligible for Local Agent execution when:

- it belongs to an **authorized project** (e.g. `AgentOps`),
- it is in a **startable state** (e.g. `Backlog` or `Todo`), not
  `Done` / `Canceled` / `In Progress`,
- it is **not already claimed** by an active LoopX goal/lease,
- it has a **machine-readable description** (id, objective, boundaries).

### 3.3 Duplicate claim prevention

To avoid two agents claiming the same task:

- The Worker never claims. It only reports.
- Claiming is done by the **Master Agent** through LoopX
  (`register-agent` + `todo add` + optional `task-lease`).
- LoopX's exclusive claim + lease TTL (validated in AGE-24 Phase 1)
  is the anti-duplicate mechanism.

## 4. Master Agent Notification Mechanism

### 4.1 Notification event

The Worker emits a structured notification:

```
TASK_DISCOVERED
  linear_issue: AGE-XX
  repo: <canonical repo>
  state: <Backlog|Todo>
  discovered_at: <ts>
```

### 4.2 Delivery channel

- The notification is written to a **local discovery queue** (a
  directory/file, e.g. `.agent-state/intake/pending/`) that the Master
  Agent polls on wake.
- The Master Agent reads the Linear Issue itself (as the source of
  truth) when it wakes — the notification is a **pointer**, not a copy.
- GPT Relay is **not** the discovery channel. GPT Relay remains the
  *review/decision* transport (Loop A). Discovery is a local event.

### 4.3 Non-interruption

The notification must not interrupt the Master Agent's current execution
context. The Master Agent checks the intake queue at the next wake /
phase boundary, not mid-phase.

## 5. LoopX Integration Boundary

### 5.1 What Task Intake creates in LoopX

On task acceptance, the Master Agent initializes LoopX state:

| LoopX artifact | Created by | Purpose |
|---|---|---|
| Goal (bootstrap) | Master Agent | durable task state |
| `ACTIVE_GOAL_STATE.md` | Master Agent | objective, todos, authority sources |
| Agent registration | Master Agent | ownership identity |
| Todo (first task) | Master Agent | initial work item |
| Execution lease (optional) | Master Agent | TTL ownership (anti-duplicate) |

### 5.2 What Task Intake does NOT create

The Worker does **not** call LoopX. It only produces the discovery
notification. LoopX initialization is the Master Agent's responsibility.

### 5.3 Synchronization

- The Linear issue id becomes the LoopX goal id convention
  (`<project>-<issue-id>-goal`).
- The Linear issue description is the source of truth for the objective.
- LoopX state and Linear state must be reconciled by the Master Agent on
  wake (read Linear → read LoopX → diff → act).

## 6. Governance and Security Rules

The Task Intake Worker is bound by the same AgentOps rules as every other
component:

- **No autonomous execution**: the Worker never executes. The Master
  Agent only executes after AgentOps policy checks.
- **No bypass of approval rules**: high-risk tasks still require a human
  gate (Phase Policy).
- **Discovery is evidence, not authorization**: a `TASK_DISCOVERED` event
  grants nothing. It is a signal that the Master Agent *may* evaluate the
  task.
- **Exact binding**: any task the Master Agent claims must be bound to the
  exact Linear issue id + repo + (eventual) PR/HEAD.
- **Fail closed**: if the Worker cannot determine eligibility, it emits no
  notification (silent) rather than a partial one.

## 7. Future Implementation Roadmap

1. **Milestone 1 — Bounded polling worker (CLI)**: a
   `task_intake_worker` CLI that scans Linear (authorized project),
   filters eligible issues, writes `TASK_DISCOVERED` notifications to the
   intake queue. No daemon; invoked by the Master Agent or a scheduler
   tick.
2. **Milestone 2 — Master Agent intake handler**: on wake, read the intake
   queue, read the Linear Issue (source of truth), initialize LoopX goal,
   claim the task.
3. **Milestone 3 — LoopX claim + lease integration**: register agent,
   add first todo, acquire execution lease (TTL) to prevent duplicate
   claims.
4. **Milestone 4 — Policy-gated execution**: wire the Phase Policy so
   high-risk discovered tasks enter `WAITING_HUMAN_GATE` and low-risk ones
   auto-continue.
5. **Milestone 5 — Validation (mirror AGE-26)**: run the sandbox flow
   "Linear Issue Created → Worker Detects → Master Agent Notified → Agent
   Claims → LoopX Tracks State → Execution".

Each milestone is a separate authorization gate; none are started by
AGE-27.

## 8. Validation Target (future)

The future validation flow AGE-27 designs:

```
Linear Issue Created
        ↓
Watcher Detects
        ↓
Master Agent Receives Notification
        ↓
Agent Claims Task
        ↓
LoopX Tracks State
```

This is the missing first segment of the AGE-26 sandbox flow.

## 9. Boundary

- Design only.
- No production deployment.
- No GPT Relay replacement.
- No autonomous execution without AgentOps policy checks.
- No daemon / scheduler / web service (deferred to a future authorized
  milestone).
- No merge, no deploy.
- Local Execution Agent role only; GPT Web remains cognitive layer.
