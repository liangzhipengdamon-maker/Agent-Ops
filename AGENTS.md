# GovernLoop Agent Instructions

When the user asks to use GovernLoop, do not rediscover the runtime from source and do not invent a replacement interaction.

## Explicit reviewer connection request

If the user explicitly asks to **connect / bind GovernLoop to a ChatGPT reviewer conversation**, do not run the normal task-readiness investigation first. Run the existing setup flow directly:

`governloop setup --repo <owner/repo>`

This launches the existing GovernLoop reviewer setup wizard. Do not replace it with an Agent-generated menu. Let the wizard ask for the exact `https://chatgpt.com/c/...` conversation URL, test the CDP connection, and bind the conversation.

Only ask the user for information the wizard genuinely needs and cannot infer, such as the exact target ChatGPT conversation URL.

## Normal governed-task flow

1. Run `governloop doctor --task-id <task> --repo <owner/repo>` from the target repository/worktree.
2. Follow exactly the single top-level `next_required_action` or `next_required_external_action` returned by doctor.
3. If an exact interactive-local task scope has already been confirmed, doctor may reuse that verified scope for readiness diagnostics when signed authority is absent. Do not create, rewrite, or broaden the task scope.
4. If doctor reports `reviewer_binding` as the next action, run the same existing setup flow:

   `governloop setup --repo <owner/repo>`

5. After reviewer binding is ready, use the existing Interactive Local task flow. At a genuine pending `REVIEW` gate, GovernLoop relays the exact-bound review request automatically.
6. Never infer Ready, Merge, Release, or Deploy authority from task scope, review PASS, CI, runtime state, or relay ACK. Those remain separate explicit Product Owner decisions.

## Interaction principle

- Reuse existing GovernLoop mechanisms before investigating architecture.
- No blocker evidence -> no new architecture.
- One blocker -> one minimal fix.
- Explicit connection request -> launch the existing setup wizard, not doctor/source-code archaeology.
