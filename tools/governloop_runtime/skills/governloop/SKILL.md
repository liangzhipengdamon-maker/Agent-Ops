---
name: governloop
description: Use GovernLoop to run coding tasks from the correct Git repository or worktree, confirm Interactive Local scope in the host, continue automatically within approved scope, hand genuine REVIEW gates to the configured GPT reviewer, and stop for Product Owner or lifecycle authorization.
compatibility: OpenCode global skill
metadata:
  governloop/source: "canonical"
  governloop/issue: "64"
---

# GovernLoop

Use this skill when the user asks to use GovernLoop, continue a GovernLoop task, or run a governed coding task.

## 1. Start from the correct project

- Work from the target repository/worktree, not from the GovernLoop source repository unless the task is itself about GovernLoop.
- Before starting, verify the current Git root and `remote.origin.url` match the project the user intends to change.
- If the task names a different project than the current Git root, do not govern the wrong repository. Move to the correct existing repo/worktree when its path is known; otherwise ask only for the missing target path.
- Do not use a governance/planning repository as the execution directory for another repository's source changes.

## 2. Enter GovernLoop immediately

Run:

`governloop start`

If GovernLoop returns `TASK_ID_REQUIRED`, reuse the existing task ID already present in the task/context. If none exists, ask only for the task ID. Never invent one from a branch name, commit, issue title, or guess.

Follow exactly one `NEXT_REQUIRED_ACTION`, `next_required_action`, or `next_required_external_action` at a time. Do not preflight hypothetical later blockers.

## 3. Interactive Local scope

When GovernLoop requires `setup-task-scope`:

1. Present the exact task scope to the user in the OpenCode host interaction.
2. After the user explicitly approves that exact scope, rerun the same `setup-task-scope` command with `--host-confirm`.
3. Do not send the user to a separate Terminal just to type `YES`.
4. Never use `--host-confirm` before explicit approval of the exact displayed scope.

Interactive Local is a same-user/same-uid trust boundary. Host confirmation is provenance, not signed lifecycle authority.

## 4. Continue automatically inside scope

After task scope is confirmed, continue the task without asking the user to approve ordinary scope-in work repeatedly.

Loop on the existing GovernLoop result:

1. Execute the single permitted next action.
2. Re-run the appropriate GovernLoop check/runner for the same task.
3. Continue while the action remains inside the confirmed scope and no Product Owner gate is reached.

Do not create a new daemon, scheduler, approval store, or control plane to implement this loop. The coding-agent session is the loop driver; GovernLoop remains the gatekeeper.

## 5. Review and stop conditions

- At a genuine `REVIEW` gate, use GovernLoop's existing automatic GPT review handoff. Do not ask the user to copy/paste the review report when the configured handoff path is available.
- Continue after the review only when GovernLoop reports the next permitted action.
- Stop and ask the user when GovernLoop reaches a real Product Owner decision or lifecycle gate.
- Ready, Merge, Release, Deploy, tag, close, or equivalent lifecycle transitions require their existing separate explicit authorization.
- Never infer lifecycle authorization from task scope, `--host-confirm`, CI success, review PASS, runtime state, setup success, or relay ACK.

## 6. Minimal-blocker rule

No blocker evidence, no new architecture. One blocker, one minimal patch. Reuse existing GovernLoop authority, transport, review, and lifecycle paths before adding any new mechanism.
