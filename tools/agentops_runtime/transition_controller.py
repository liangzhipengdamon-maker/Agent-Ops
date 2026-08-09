#!/usr/bin/env python3
"""AGE-24 / AGE-29 transition controller (risk -> routing + state writeback).

Combines a risk decision (AGE-29) and a review decision (AGE-28) into a
routing outcome:

  - HIGH risk                 -> WAITING_PO_AUTH (PO final; never auto-merge)
  - MEDIUM risk               -> GPT_DECISION_REQUIRED (must ask GPT Web)
  - LOW risk + PASS review    -> AUTO_CONTINUE
  - LOW risk + CHANGES_REQUESTED -> FOLLOW_UP_REQUIRED
  - LOW risk + INCOMPLETE     -> WAIT_REVIEW (incomplete evidence)

Governance boundaries:
- The controller NEVER grants merge/deploy permission.
- PO authorization is never bypassed for HIGH risk.
- Review evidence is not authorization.
"""

import dataclasses
import json
import os
import time
from typing import Optional


@dataclasses.dataclass(frozen=True)
class TransitionOutcome:
    route: str  # WAITING_PO_AUTH | GPT_DECISION_REQUIRED | AUTO_CONTINUE | FOLLOW_UP_REQUIRED | WAIT_REVIEW
    risk: str
    review: str
    reason: str

    def to_record(self) -> dict:
        return {
            "route": self.route,
            "risk": self.risk,
            "review": self.review,
            "reason": self.reason,
        }


def route_decision(risk_level: str, review_decision: str) -> TransitionOutcome:
    """Pure routing function (no side effects)."""
    if risk_level == "HIGH":
        return TransitionOutcome(
            route="WAITING_PO_AUTH", risk=risk_level, review=review_decision,
            reason="high_risk_requires_po_authorization")
    if risk_level == "MEDIUM":
        return TransitionOutcome(
            route="GPT_DECISION_REQUIRED", risk=risk_level, review=review_decision,
            reason="medium_risk_requires_gpt_web_judgment")
    # LOW risk path
    if review_decision == "PASS":
        return TransitionOutcome(
            route="AUTO_CONTINUE", risk=risk_level, review=review_decision,
            reason="low_risk_and_review_pass")
    if review_decision == "CHANGES_REQUESTED":
        return TransitionOutcome(
            route="FOLLOW_UP_REQUIRED", risk=risk_level, review=review_decision,
            reason="review_changes_requested")
    # INCOMPLETE / BLOCKED / COMMENTED
    return TransitionOutcome(
        route="WAIT_REVIEW", risk=risk_level, review=review_decision,
        reason=f"incomplete_review_evidence_{review_decision}")


def write_state(outcome: TransitionOutcome, task_state_path: str) -> str:
    """Append the transition outcome to the durable task-state file.

    Returns the path written. Fail-open only for the local record; the
    caller must not treat a write failure as a permission grant.
    """
    os.makedirs(os.path.dirname(task_state_path) or ".", exist_ok=True)
    state = {"outcome": outcome.to_record(), "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with open(task_state_path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    return task_state_path
