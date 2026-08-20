# GovernLoop Agent Safety Contract

This contract defines the minimal authorization boundary for any local agent using GovernLoop, including OpenCode, WorkBuddy, Codex, and similar tools.

GovernLoop is transport. Transport success does not authorize repository mutation.

## Authorization model

GovernLoop uses a scoped-authorization model, not a per-stage re-confirmation
model.

- When the user explicitly authorizes execution of one clearly scoped task, the
  agent may continue within that same scope through the full lifecycle:
  implementation → commit/push → PR → Ready → merge. It does not need to stop
  and re-request authorization at each individual stage.
- Authorization is scoped to the task as granted. It does NOT extend to:
  - a material change in scope or a follow-up issue;
  - deploy or release;
  - tag, force push, or direct rewrite of `main`;
  - any destructive or high-risk action.
- STOP and require fresh explicit authorization when any of these occur:
  material scope change, unexpected HEAD/main drift, merge conflict, P0/P1
  blocker, or a destructive/high-risk action.

Keep these stages conceptually distinct for verification and reporting:

1. implementation / repository modification
2. commit and push
3. pull request creation
4. Ready for review
5. merge
6. deploy or release

Do not infer Ready, merge, deploy, release, or follow-up work from:
- review PASS or APPROVED
- relay success
- test PASS
- PR mergeability
- PR Ready state
- task completion
- authorization granted for an earlier stage within a different scope

## Before Ready, merge, deploy, or release

During an authorized in-scope flow, before executing the requested stage:

1. read the current remote state;
2. verify the exact target object;
3. for PR lifecycle actions, verify the exact current PR HEAD where applicable;
4. stop if the remote state drifted in a way that invalidates the authorization target.

If authorization for the flow is absent, STOP and report the current state. Do
not continue automatically.

## Scope

Do not broaden implementation scope, start a follow-up issue, begin a later phase, or mutate another repository unless explicitly requested or authorized.

Do not treat a plan, review result, test result, deployment preview, or status report as mutation authority.

## Main branch protection

Do not directly push, rewrite, force-push, or otherwise mutate `main` unless the user explicitly authorizes that exact action.

Prefer ordinary branch + PR workflows when repository mutation is authorized.

## GovernLoop transport success

A diagnostic CDP read-back is not canonical relay success.

Canonical relay success requires the relay itself to complete successfully and write its canonical output. A probe may be used only for diagnosis or verification after the relay result is known.

## Minimal-transport boundary

Do not restore or require the historical AgentOps lifecycle runtime, authority engine, watcher/controller, strict ACK envelope, host-confirm, `setup-task-scope`, or similar governance machinery merely to enforce this contract.

This contract is intentionally thin: keep GovernLoop as Minimal Transport, and enforce mutation authorization at the agent action boundary.
