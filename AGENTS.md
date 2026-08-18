# GovernLoop Agent Instructions

All local agents working in this repository must follow the shared authorization boundary in:

`docs/ops/AGENT_SAFETY_CONTRACT.md`

Key rules:

- GovernLoop transport success does not authorize repository mutation.
- Implementation, commit/push, PR creation, Ready, merge, and deploy/release are separate authorization stages.
- Never infer a later-stage authorization from PASS, relay success, test success, mergeability, Ready state, task completion, or an earlier-stage authorization.
- Before Ready, merge, deploy, or release, verify current remote state and the exact target/HEAD where applicable, then require explicit user authorization for that stage.
- If authorization for the next stage is absent, STOP and report current state; do not auto-continue.
- Do not broaden scope or start follow-up work without explicit authorization.
- Do not directly push/rewrite/force-push `main` without explicit authorization for that exact action.
- Diagnostic CDP read-back is not canonical relay success; canonical success requires relay exit success plus canonical output written.
- Do not reintroduce the historical AgentOps lifecycle/authority/runtime stack just to enforce these rules.
