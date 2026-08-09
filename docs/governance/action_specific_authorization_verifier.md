# Action-Specific Authorization Verifier

**Status: Historical / optional compatibility component.**

This verifier is not part of the current default control flow and must not add per-action stops to an `AUTO` or `MANUAL` task.

If a future task explicitly requires an action-specific verifier, that task must define the exact gate and scope. Otherwise, execution follows `docs/governance/CURRENT_RUNTIME_RULES.md` only.
