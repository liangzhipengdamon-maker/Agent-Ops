# GovernLoop Agent Safety Contract

This contract defines the minimal authorization boundary for any local agent using GovernLoop, including OpenCode, WorkBuddy, Codex, and similar tools.

GovernLoop is transport. Transport success does not authorize repository mutation.

## Separate authorization stages

Treat each of the following as a separate stage:

1. implementation / repository modification
2. commit and push
3. pull request creation
4. Ready for review
5. merge
6. deploy or release

Authorization for one stage never implies authorization for a later stage.

Do not infer Ready, merge, deploy, release, or follow-up work from:
- review PASS or APPROVED
- relay success
- test PASS
- PR mergeability
- PR Ready state
- task completion
- authorization granted for an earlier stage

## Before Ready, merge, deploy, or release

Before executing the requested stage:

1. read the current remote state;
2. verify the exact target object;
3. for PR lifecycle actions, verify the exact current PR HEAD where applicable;
4. require explicit user authorization for that stage;
5. stop if the remote state drifted in a way that invalidates the authorization target.

If authorization for the next stage is absent, STOP and report the current state. Do not continue automatically.

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
