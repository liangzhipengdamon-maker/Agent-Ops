# Agent-Ops Builder ↔ GPT Auto Review Handoff

This directory contains the minimal protocol files for the automated review handoff between the Builder Agent and the GPT Reviewer.

## Contract & Rules
1. **No PR Contents in status**: The `status.json` file ONLY holds the pointer (Repo, PR number, HEAD SHA). The GPT Reviewer is responsible for reading the diff directly from GitHub.
2. **One-Way State Machine**: 
   `IDLE` → `REVIEW_REQUESTED` → `WAITING_FOR_REVIEW` → (`CHANGES_REQUESTED` / `BLOCKED`)
   If the GPT provides a `PASS` verdict, the state transitions directly to `WAITING_PO_AUTH`. **PASS does NOT automatically grant Ready/Merge authorization.** (Note: `PASS` is purely a verdict, not a durable machine state in itself).
3. **Stale Review Prevention (Triple-Binding)**: The `gpt-review.md` MUST contain the exact `HEAD` SHA. During processing, the relay MUST verify that:
   `Review HEAD == Status.json HEAD == GitHub Remote Current HEAD`. 
   If any of these three drift, the review is discarded (Fail-Closed) and the state refuses to transition.
4. **No External Relay Modification**: The `scripts/relay_adapter.py` acts as a repository-local driver. External global `relay.py` processes monitor `status.json` and must supply the exact remote HEAD.

## Files
- `status.json`: Contains the current state of the review request.
- `gpt-review.md`: The output from the GPT Reviewer (created during handoff).

## Usage for External Relay
1. Run `python scripts/relay_adapter.py` to check for `REVIEW_REQUESTED`.
2. Capture the printed minimal payload and send it to the GPT Reviewer.
3. Save the GPT response to `.agent-bridge/gpt-review.md`.
4. Check GitHub for the true current PR HEAD SHA.
5. Run `python scripts/relay_adapter.py process_review --current-head <FULL_SHA>` to process the verdict safely.
