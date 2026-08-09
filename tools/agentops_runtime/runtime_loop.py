#!/usr/bin/env python3
"""Thin AUTO/MANUAL runtime adapter (AGE-30).

Deletion-first: this is ONLY the decision glue. Durable state belongs to
LoopX (refresh-state); GPT Web transport belongs to the existing Neutral
Relay; GitHub/Linear reads are thin adapters.

AUTO: review fail -> findings handed to the Builder execution chain;
PASS -> continue until acceptance. MANUAL: pause only at the named
checkpoint. No parallel JSON/PID state kernel, no risk classifier.
"""

import subprocess
import time
from typing import Optional

from . import linear_adapter
from .task_intake import spec_from_linear
from .review_intake import read_github_pr, read_pr_head
from . import relay_client


def _loopx_refresh(task_id: str, phase: str, pr: str):
    """Durable operational state via LoopX (refresh-state). Best effort;
    never a parallel kernel."""
    try:
        subprocess.run(
            ["loopx-canary", "refresh-state", "--goal-id", task_id,
             "--project", ".", "--classification", "agentops_runtime",
             "--next-action", phase, "--agent-id", f"agent-{pr}"],
            capture_output=True, text=True, timeout=30)
    except Exception:
        pass


def decide(task_id: str, repo: str, pr: str) -> dict:
    """One bounded decision step.

    Returns {phase, review_decision, findings, checkpoint_reached}.
    Phases: INTAKE | REVIEW | FIX | PASSED | COMPLETE | WAITING_PO_AUTH |
    BLOCKED | TERMINAL.
    """
    spec = spec_from_linear(task_id)
    if spec is None:
        return {"phase": "BLOCKED", "review_decision": "LINEAR_UNREADABLE",
                "findings": [], "checkpoint_reached": False,
                "decision_request": "cannot read Linear task"}
    if not spec.mode:
        return {"phase": "BLOCKED", "review_decision": "MODE_MISSING",
                "findings": [], "checkpoint_reached": False,
                "decision_request": "specify Execution Mode AUTO|MANUAL"}

    head = read_pr_head(repo, int(pr)) or ""
    review = read_github_pr(repo, int(pr), head)
    outcome = {
        "mode": spec.mode,
        "phase": "REVIEW",
        "review_decision": review.decision,
        "findings": review.findings,
        "checkpoint_reached": False,
        "head": head,
    }

    # Terminal: PR closed/merged.
    gh_state = _pr_state(repo, int(pr))
    if gh_state is None:
        outcome["phase"] = "BLOCKED"      # unreadable remote -> retryable
        outcome["review_decision"] = "UNREADABLE_REMOTE"
        _loopx_refresh(task_id, "BLOCKED", pr)
        return outcome
    if gh_state.get("state") in ("MERGED", "CLOSED"):
        outcome["phase"] = "TERMINAL"
        _loopx_refresh(task_id, "TERMINAL", pr)
        return outcome

    # Linear task closed/canceled -> terminal.
    lin = linear_adapter.read_linear_issue(task_id)
    if lin and (lin.get("state_type") in ("canceled", "completed")
                or lin.get("state_name") in ("Canceled", "Done")):
        outcome["phase"] = "TERMINAL"
        _loopx_refresh(task_id, "TERMINAL", pr)
        return outcome

    if review.decision in ("CHANGES_REQUESTED", "NOT_PASS"):
        outcome["phase"] = "FIX"          # findings -> Builder execution chain
    elif review.decision == "PASS":
        # MANUAL: pause only at the named checkpoint (current-HEAD PASS).
        if spec.mode == "MANUAL" and spec.checkpoint:
            outcome["phase"] = "WAITING_PO_AUTH"
            outcome["checkpoint_reached"] = True
        else:
            outcome["phase"] = "PASSED"   # AUTO: continue until acceptance

    _loopx_refresh(task_id, outcome["phase"], pr)
    return outcome


def _pr_state(repo: str, pr: int) -> Optional[dict]:
    import json
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json", "state"],
            capture_output=True, text=True, check=True, timeout=30)
        return json.loads(res.stdout)
    except Exception:
        return None
