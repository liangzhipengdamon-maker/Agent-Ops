# AGE-21 Long Task Automation Pilot — Retrospective

> Documentation-only retrospective of the AGE-21 pilot execution attempt
> (PR #19, branch `pilot/age-21-long-task-automation`, HEAD `91a7495`).
> Records the automation gaps observed during the pilot run. No
> implementation, no runtime, no scheduler, no database.

## 1. Pilot scope executed

The AGE-21 pilot artifact was:

- a single docs-only file `docs/pilots/AGE-21_PILOT_ENTRY.md`
- on a Draft PR (#19)
- submitted to CI (test job PASS on HEAD `91a7495715ee549716d3c14934635263401fbde5`)
- followed by an Independent Review Request sent through the Neutral Relay
  on the isolated AgentOps runtime (CDP 9233, profile `~/.agentops/chrome-profile`)

The full governance flow was exercised end-to-end:

```
Task Intake (AGE-21 from Linear)
  -> Planning (this docs-only scope)
  -> Implementation (one file added)
  -> CI (PASS on exact HEAD)
  -> Independent Review (Neutral Relay on AgentOps 9233)
  -> WAITING_PO_AUTH (PR #19 is Ready, not merged)
```

## 2. Automation gaps observed

During the pilot, several operational gaps were observed that prevent fully
unattended execution. Each gap is recorded as a **gap**, not as a fix.

### 2.1 Execution continuity gap

- The Neutral Relay run timed out on `WAIT_ASSISTANT_RESPONSE` (180 s) while
  waiting for the GPT reviewer to acknowledge the formal `independent_review`
  ACK format.
- The message *was* delivered to the canonical conversation (AgentOps 9233,
  `6a74f5c0`), but the strict correlation format (all four fields on single
  lines) did not match GPT's narrative response on this run.
- **Gap**: there is no bounded, recoverable, retryable capture loop that
  distinguishes "GPT is still typing" from "GPT responded in an unexpected
  format" from "GPT will not respond". A retryable acknowledge requires a
  bounded wait + format-tolerant capture + state checkpoint.

### 2.2 Resumability / interruption-survival gap

- The pilot ran as a single end-to-end execution. If the agent process is
  interrupted between the CI pass and the Neutral Relay send, the next run
  has to rediscover the PR HEAD, re-run the identity check, and re-issue the
  review request — by hand.
- There is no persistent intermediate state (e.g., `WAITING_REVIEW` /
  `WAITING_REVIEW_ACK`) recorded alongside the agent state.
- **Gap**: agent state transitions across the governance flow are not
  checkpointed. A restart cannot resume from "sent the review request, now
  waiting for the ACK".

### 2.3 Cross-process memory of recent activity

- During the pilot, the Neutral Relay had to be re-run because the first send
  appeared to fail. The re-run relied on the on-disk `AGENTOPS_MARKER` file
  and the conversation URL alone. The agent had to rediscover that PR #19's
  HEAD had not changed, and that the review request had not been ACK'd.
- **Gap**: there is no "what did we do last time for this Linear issue"
  record. An agent restart must re-derive everything from the live state
  (git, Linear, GitHub PR, Neutral Relay status) on every run.

### 2.4 Review-ACK parsing gap

- The strict correlation parser requires:
    - `REVIEW_REQUEST_ID:` `<value>` on one line
    - `REPO:` `<value>` on one line
    - `PR:` `<value>` on one line
    - `HEAD:` `<value>` on one line
    - `ACK: status_report_received` for ACK confirmation
- The actual GPT reviewer in this pilot run produced a **narrative**
  acknowledgment that does not match this single-line format (values appear
  on the next line, `PR:` carries a `#` prefix, `REPO:` is omitted, no
  `ACK:` marker).
- The relay correctly **fail-closed** (the strict correlation is the
  documented contract). The pilot then relied on a human or a follow-up
  reviewer run to interpret the narrative.
- **Gap**: there is no tolerant parser that can distinguish "strictly bound
  ACK" from "narrative acknowledgment from the same reviewer on the same
  request" without weakening the strict-correlation contract. The contract
  is correct; the gap is in the *capture* path.

### 2.5 Concurrent-request interleaving gap

- During the pilot, the conversation had a previous assistant response
  (from an earlier unrelated turn) immediately preceding the review request.
  The current strict correlation correctly requires `reviewer_id` and
  exact-binding fields and is not fooled by older content.
- **Gap**: however, when GPT produces a long multi-paragraph answer, the
  strict-correlation parser operates on the whole text and may miss
  review-only fields that are mid-paragraph. The contract does not currently
  require a per-ACK section delimiter.

### 2.6 Failure triage gap

- When the relay returned `WAIT_ASSISTANT_RESPONSE` timeout, the agent had
  to manually verify the conversation contained the user message
  (delivery OK) and that the GPT response existed (correlation format
  mismatch). This required opening the AgentOps browser runtime on CDP 9233,
  attaching, and inspecting `[data-message-author-role="..."]` nodes.
- **Gap**: there is no first-class triage output that classifies
  `WAIT_ASSISTANT_RESPONSE` timeout into:
    (a) request delivered, response pending
    (b) request delivered, response present, format mismatch
    (c) request not delivered
    (d) conversation identity drift during wait
  Each class needs a different next action; today all four look the same
  at the relay exit.

## 3. Governance integrity during the pilot

Verified during the pilot:

- Runtime isolation held: AgentOps only connected to CDP 9233; LearnMind
  CDP 9223 was untouched.
- Conversation identity binding held: `EXPECTED == MATCHED ==
  6a74f5c0-a240-83ec-9cff-198ffab1140e`.
- Duplicate-send protection held: a second relay invocation with the same
  `REVIEW_REQUEST_ID` would skip the send path.
- STOP_AND_WAIT held: the agent stopped at `WAITING_PO_AUTH` without
  attempting Ready, Merge, or Deploy.

No unauthorized mutation occurred.

## 4. Recommendations (recorded, not implemented)

These are **observations**, not plans. They do not start any implementation.

- A bounded ACK-capture loop that distinguishes "still typing", "ACK in
  strict format", and "ACK in narrative format" without weakening the
  strict-correlation contract.
- A persistent agent-state checkpoint between governance flow steps, so a
  restart can resume from the last completed step.
- A first-class triage output for relay timeouts that classifies the cause
  and suggests the next action.
- A linear-id-keyed memory of recent activity per Linear issue, so the
  agent does not re-derive the world on every run.

## 5. Final state

`WAITING_PO_AUTH` — this retrospective draft awaits PO merge authorization.
No AGE-22 started, no runtime change, no scheduler, no database, no
automation engine.