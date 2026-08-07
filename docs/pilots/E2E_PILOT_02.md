# E2E Pilot 02

Purpose:
Validate the normal AgentOps review handoff path.

Expected path:

Draft PR
→ REVIEW_REQUESTED
→ Neutral Relay
→ External ChatGPT Reviewer
→ PASS
→ WAITING_PO_AUTH
→ STOP

Governance:
- This file is a transport/review fixture only.
- PASS is not merge authorization.
- No automatic Ready, Merge, Deploy, or Linear mutation.
