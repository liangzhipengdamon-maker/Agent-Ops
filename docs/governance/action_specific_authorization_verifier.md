# Action-Specific Authorization Verifier

The verifier protects concrete protected actions; it is not a per-edit brake on ordinary work inside an already authorized task/scope.

Rules:

- Protected-action authority comes only from explicit Product Owner authorization.
- PASS, CI, Linear state, reports, timers, transport success, and Agent suggestions never create permission.
- Implementation permission does not imply Ready, Merge, Deploy, force push, production access, or authorization-policy changes.
- Missing, stale, ambiguous, expired, revoked, or mismatched authorization fails closed.
- Protected actions acting on an existing commit bind the exact live HEAD required by that gate.
- Risk routing and authorization verification are separate; neither may replace the other.

Current control semantics: `docs/governance/CURRENT_RUNTIME_RULES.md`.
