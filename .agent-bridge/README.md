# Agent-Ops Builder ↔ GPT Auto Review Handoff

This directory contains the minimal protocol files for the automated review handoff between the Builder Agent and the GPT Reviewer.

## Contract & Rules
1. **No PR Contents in status**: The `status.json` file ONLY holds the pointer (Repo, PR number, HEAD SHA). The GPT Reviewer is responsible for reading the diff directly from GitHub.
2. **One-Way State Machine**: 
   `IDLE` → `REVIEW_REQUESTED` → `WAITING_FOR_REVIEW` → (`PASS` / `CHANGES_REQUESTED` / `BLOCKED`)
   If `PASS`, it transitions to `WAITING_PO_AUTH`. **PASS does NOT automatically grant Ready/Merge authorization.**
3. **Stale Review Prevention**: The `gpt-review.md` MUST contain the exact `HEAD` SHA. If the `HEAD` in `gpt-review.md` does not match the current `status.json`, the review is discarded.
4. **No External Relay Modification**: The `scripts/relay_adapter.py` acts as a repository-local driver. External global `relay.py` processes simply need to monitor `status.json` and execute `python scripts/relay_adapter.py process_review` when a `gpt-review.md` is dropped in.

## Files
- `status.json`: Contains the current state of the review request.
- `gpt-review.md`: The output from the GPT Reviewer (created during handoff).

## Usage for External Relay
1. Run `python scripts/relay_adapter.py` to check for `REVIEW_REQUESTED`.
2. Capture the printed minimal payload and send it to the GPT Reviewer.
3. Save the GPT response to `.agent-bridge/gpt-review.md`.
4. Run `python scripts/relay_adapter.py process_review` to process the verdict and update `status.json`.
