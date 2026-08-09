# AGE-3 Authority & Mission Authorization Design

**Status: Historical / Superseded.**

The original design remains available in Git history but is not a current runtime contract.

Retained principles only:

- Product Owner is the authorization authority for protected actions.
- Review/CI/Linear/runtime signals are evidence, not authorization.
- Fail closed on ambiguity, stale state, or authorization mismatch.
- Protected actions acting on an existing commit use the exact live HEAD required by the current gate.

Universal one-action-per-wake, terminal intermediate states, and future-final-HEAD requirements for ordinary implementation are superseded.

Current rules: `docs/governance/CURRENT_RUNTIME_RULES.md`.
