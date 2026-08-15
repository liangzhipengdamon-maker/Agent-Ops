# GovernLoop Agent Instructions

When the user asks to use GovernLoop, do not rediscover the runtime from source and do not invent a replacement interaction. The user should state intent; GovernLoop should discover local context.

## A. Normal governed task

If the user asks to **use GovernLoop for this task**:

1. From the target Git repository/worktree, immediately run:

   `governloop start`

2. GovernLoop resolves `owner/repo` from the current Git `origin`. Do not ask the user for the repository when it is already resolvable.
3. If `start` returns `TASK_ID_REQUIRED`, use the existing task ID already present in the task/current context and rerun:

   `governloop start --task-id <task>`

4. If no task ID exists in the task/current context, ask the user **only** for that task ID. Do not infer or invent one from branch names, commits, issue text, or guesswork.
5. Follow exactly the single `NEXT_REQUIRED_ACTION`, `next_required_action`, or `next_required_external_action` returned by GovernLoop. Do not preflight hypothetical later blockers.
6. If an exact Interactive Local task scope has already been confirmed, the existing doctor/runtime path may reuse it diagnostically. Do not create, rewrite, or broaden it from inference.
7. At a genuine pending `REVIEW` gate, GovernLoop uses the existing exact-bound review handoff path.
8. Never infer Ready, Merge, Release, or Deploy authority from task scope, review PASS, CI, runtime state, setup success, or relay ACK. Those remain separate explicit Product Owner decisions.

## B. Explicit reviewer connection request

If the user explicitly asks to **connect / bind GovernLoop to a ChatGPT reviewer conversation**:

1. From the target Git repository/worktree, immediately run:

   `governloop setup`

2. GovernLoop resolves `owner/repo` from the current Git `origin`, owns startup/reuse of the dedicated browser runtime, and launches the existing localhost setup wizard.
3. **Do not preflight or invent** Chrome launch commands, CDP ports, browser profiles, setup-server ports, relay/config paths, source-code investigation, `doctor`, Linear checks, or authority checks before setup.
4. Let setup produce the first real blocker. If it returns `NEXT_REQUIRED_ACTION`, address exactly that one blocker and rerun the same setup command. Do not solve hypothetical later blockers.
5. In the wizard, user action is limited to: sign in/open the exact ChatGPT reviewer conversation if needed, paste its exact `https://chatgpt.com/c/...` URL, press **Test Connection**, then **Bind Conversation**.
6. Do not replace this with an Agent-generated menu or manual relay/browser architecture.

## Interaction principle

- Normal task -> `governloop start`; do not manually assemble repo arguments first.
- Explicit reviewer connection -> `governloop setup`; do not run doctor first.
- Missing information -> ask only for the one item GovernLoop reports as missing.
- No blocker evidence -> no speculative step or new architecture.
- One real blocker -> one exact next action.
- Reuse existing GovernLoop mechanisms before investigating architecture.
