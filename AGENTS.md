# GovernLoop Agent Instructions

When the user asks to use GovernLoop, do not rediscover the runtime from source and do not invent a replacement interaction. First classify the user's intent into exactly one of the two paths below.

## A. Explicit reviewer connection request

If the user explicitly asks to **connect / bind GovernLoop to a ChatGPT reviewer conversation**:

1. Determine only the target repository (`owner/repo`). If it is already clear from the user's request/current project, do not ask again.
2. Immediately run:

   `governloop setup --repo <owner/repo>`

3. **Do not preflight or invent** Chrome launch commands, CDP ports, browser profiles, setup-server ports, relay/config paths, source-code investigation, `doctor`, Linear checks, or authority checks before setup.
4. `governloop setup` owns startup/reuse of the dedicated GovernLoop browser runtime and launches the existing localhost setup wizard.
5. Let setup produce the first real blocker. If it returns `NEXT_REQUIRED_ACTION`, address exactly that one blocker and rerun the same setup command. Do not solve hypothetical later blockers.
6. In the wizard, user action is limited to: sign in/open the exact ChatGPT reviewer conversation if needed, paste its exact `https://chatgpt.com/c/...` URL, press **Test Connection**, then **Bind Conversation**.
7. Do not replace this with an Agent-generated menu or manual relay/browser architecture.

## B. Normal governed-task flow

For a normal governed task that is **not** an explicit reviewer-connection request:

1. Run `governloop doctor --task-id <task> --repo <owner/repo>` from the target repository/worktree.
2. Follow exactly the single top-level `next_required_action` or `next_required_external_action` returned by doctor.
3. If an exact interactive-local task scope has already been confirmed, doctor may reuse that verified scope for readiness diagnostics when signed authority is absent. Do not create, rewrite, or broaden the task scope.
4. If doctor reports `reviewer_binding` as the next action, run the same existing setup flow:

   `governloop setup --repo <owner/repo>`

5. After reviewer binding is ready, use the existing Interactive Local task flow. At a genuine pending `REVIEW` gate, GovernLoop relays the exact-bound review request automatically.
6. Never infer Ready, Merge, Release, or Deploy authority from task scope, review PASS, CI, runtime state, setup success, or relay ACK. Those remain separate explicit Product Owner decisions.

## Interaction principle

- Explicit reviewer connection request -> run setup immediately; do not run doctor first.
- GovernLoop setup owns its browser/runtime setup; the Agent does not invent one.
- No blocker evidence -> no speculative step or new architecture.
- One real blocker -> one exact next action.
- Reuse existing GovernLoop mechanisms before investigating architecture.
