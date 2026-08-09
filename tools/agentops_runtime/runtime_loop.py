#!/usr/bin/env python3
"""Thin AUTO/MANUAL runtime adapter (AGE-30).

Deletion-first: this is ONLY the decision glue. Durable state belongs to
LoopX (refresh-state); GPT Web transport belongs to the existing Neutral
Relay; GitHub/Linear reads are thin adapters; Builder handoff uses the
existing `.agent-bridge` wake files.

AUTO: review fail -> findings handed to the Builder execution chain
(`.agent-bridge` wake) -> new code HEAD -> review again. PASS -> continue
until acceptance. MANUAL: pause only at the named checkpoint (an evaluated
condition), and resume from the PO decision. No parallel JSON/PID state
kernel, no risk classifier.
"""

import json
import os
import re
import subprocess
import time
from typing import Optional

from . import linear_adapter
from .task_intake import spec_from_linear, evaluate_checkpoint
from .review_intake import read_github_pr, read_pr_head
from . import relay_client


def _bridge_dir() -> str:
    return os.environ.get("AGENT_BRIDGE_DIR", ".agent-bridge")


def builder_handoff(task_id: str, repo: str, pr: str, head: str,
                    phase: str, findings: list) -> dict:
    """Wake the existing Builder execution chain via the `.agent-bridge`
    protocol (status.json + findings.md). This is the established Builder
    handoff (AGENT_RUNNER_PROMPT.md); the runtime does not re-implement a
    Builder, it hands findings to the existing one. Fail-closed: any I/O
    error returns ok=False so the caller can surface it."""
    bd = _bridge_dir()
    try:
        os.makedirs(bd, exist_ok=True)
        status = {
            "protocol_version": "1",
            "state": phase,
            "repo": repo,
            "pr": str(pr),
            "head": head,
            "request": "review",
        }
        with open(os.path.join(bd, "status.json"), "w") as f:
            json.dump(status, f, indent=2)
        with open(os.path.join(bd, "findings.md"), "w") as f:
            f.write("\n\n---\n\n".join(findings) if findings else "")
        return {"ok": True, "state": phase, "bridge": bd}
    except OSError as e:
        return {"ok": False, "state": phase, "bridge": bd,
                "detail": str(e)}


def _loopx_refresh(task_id: str, phase: str, pr: str) -> dict:
    """Durable operational state via LoopX (refresh-state). Returns
    {ok, detail} so failures are observable (P1-1): a failed LoopX refresh is
    surfaced as degraded, never silently swallowed."""
    try:
        res = subprocess.run(
            ["loopx-canary", "refresh-state", "--goal-id", task_id,
             "--project", ".", "--classification", "agentops_runtime",
             "--next-action", phase, "--agent-id", f"agent-{pr}"],
            capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            return {"ok": True, "detail": "refresh-state ok"}
        return {"ok": False,
                "detail": (res.stderr or res.stdout or "").strip()[-200:]}
    except Exception as e:
        return {"ok": False, "detail": f"loopx unavailable: {e}"}


def _po_decision(task_id: str, repo: str, pr: str, head: str,
                 reviews: list) -> Optional[str]:
    """PO decision intake at a MANUAL checkpoint. The decision is a formal
    review at the exact current HEAD carrying `PO_DECISION: <APPROVE|REJECT|CHANGES>`
    or a `po_decision.json` bridge file. Returns None when no decision for
    this exact PR+HEAD exists (loop stays in WAITING_PO_AUTH)."""
    for r in reviews or []:
        body = r.get("body") or ""
        if "PO_DECISION:" not in body:
            continue
        m = re.search(r"HEAD:\s*(\S+)", body)
        binds = (m and m.group(1).strip().lower() == head.lower())
        commit = (r.get("commit_id") or "").lower()
        if not commit:
            commit = ((r.get("commit") or {}).get("oid") or "").lower()
        binds = binds or (commit and commit == head.lower())
        if not binds:
            continue
        m = re.search(r"PO_DECISION:\s*(\w+)", body)
        if m:
            return m.group(1).upper()
    pj = os.path.join(_bridge_dir(), "po_decision.json")
    try:
        with open(pj) as f:
            d = json.load(f)
        if (d.get("repo") == repo and str(d.get("pr")) == str(pr)
                and d.get("head") == head):
            return str(d.get("decision", "")).upper() or None
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _checkpoint_reached(spec, review) -> bool:
    """P0-2: MANUAL pauses only at the task's NAMED checkpoint, evaluated as
    a real condition against an explicit runtime stage. The checkpoint text
    must map to a supported stage (e.g. REVIEW_PASS) AND the current-HEAD
    review must be PASS. Unevaluable checkpoint text fails closed as BLOCKED
    (caller), never silently treated as reached."""
    if not spec.checkpoint:
        return False
    if evaluate_checkpoint(spec.checkpoint) != "REVIEW_PASS":
        return False
    return review.decision == "PASS"


def _checkpoint_evaluable(spec) -> bool:
    """True when the named checkpoint maps to a supported runtime stage."""
    return evaluate_checkpoint(spec.checkpoint) is not None


def _accepted_completion(repo: str, pr: str, head: str) -> bool:
    """Accepted-completion evidence from the bridge: a completion.json bound
    to the exact PR+HEAD (written by the Builder when acceptance is
    satisfied) or a status.json in state DONE/COMPLETE for this exact
    PR+HEAD. P0-1: PASS/APPROVE produces COMPLETE only from evidence, not
    from a bare verdict."""
    bd = _bridge_dir()
    for fname, key in (("completion.json", "completion"),
                       ("status.json", "state")):
        p = os.path.join(bd, fname)
        try:
            with open(p) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if (d.get("repo") == repo and str(d.get("pr")) == str(pr)
                and d.get("head") == head
                and str(d.get(key, "")).upper() in ("DONE", "COMPLETE")):
            return True
    return False


def decide(task_id: str, repo: str, pr: str) -> dict:
    """One bounded decision step.

    Returns {phase, review_decision, findings, checkpoint_reached,
    builder, loopx}. Phases: INTAKE | REVIEW | FIX | PASSED | COMPLETE |
    WAITING_PO_AUTH | BLOCKED | TERMINAL.
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
        outcome["loopx"] = _loopx_refresh(task_id, "BLOCKED", pr)
        return outcome
    if gh_state.get("state") in ("MERGED", "CLOSED"):
        outcome["phase"] = "TERMINAL"
        outcome["loopx"] = _loopx_refresh(task_id, "TERMINAL", pr)
        return outcome

    # Linear task closed/canceled -> terminal.
    lin = linear_adapter.read_linear_issue(task_id)
    if lin and (lin.get("state_type") in ("canceled", "completed")
                or lin.get("state_name") in ("Canceled", "Done")):
        outcome["phase"] = "TERMINAL"
        outcome["loopx"] = _loopx_refresh(task_id, "TERMINAL", pr)
        return outcome

    pr_json = _pr_json_full(repo, int(pr))
    reviews = (pr_json or {}).get("reviews") or []

    if review.decision in ("CHANGES_REQUESTED", "NOT_PASS"):
        outcome["phase"] = "FIX"          # findings -> Builder execution chain
        outcome["builder"] = builder_handoff(
            task_id, repo, pr, head, "BUILDER_FIXING", review.findings)
    elif review.decision == "PASS":
        if spec.mode == "MANUAL":
            if not _checkpoint_evaluable(spec):
                # P0-2: unevaluable checkpoint -> fail closed, do not pause.
                outcome["phase"] = "BLOCKED"
                outcome["review_decision"] = "CHECKPOINT_UNEVALUABLE"
                outcome["decision_request"] = (
                    f"MANUAL checkpoint '{spec.checkpoint}' cannot be "
                    "evaluated; name a supported stage (e.g. review "
                    "approval)")
            elif _checkpoint_reached(spec, review):
                outcome["checkpoint_reached"] = True
                po = _po_decision(task_id, repo, pr, head, reviews)
                if po == "APPROVE":
                    # P0-1: resume and wake the Builder to continue.
                    if _accepted_completion(repo, pr, head):
                        outcome["phase"] = "COMPLETE"
                    else:
                        outcome["phase"] = "PASSED"
                        outcome["po_decision"] = "APPROVE"
                        outcome["builder"] = builder_handoff(
                            task_id, repo, pr, head, "CONTINUE", [])
                elif po in ("REJECT", "CHANGES", "CHANGES_REQUESTED"):
                    outcome["phase"] = "FIX"
                    outcome["po_decision"] = po
                    outcome["builder"] = builder_handoff(
                        task_id, repo, pr, head, "BUILDER_FIXING",
                        [f"PO decision {po} at checkpoint "
                         f"{spec.checkpoint}"])
                else:
                    outcome["phase"] = "WAITING_PO_AUTH"
            else:
                outcome["phase"] = "PASSED"  # checkpoint not reached; continue
                outcome["builder"] = builder_handoff(
                    task_id, repo, pr, head, "CONTINUE", [])
        else:
            # P0-1: AUTO PASS wakes the Builder to continue in scope; accepted
            # completion is derived from evidence, not a bare PASS.
            if _accepted_completion(repo, pr, head):
                outcome["phase"] = "COMPLETE"
            else:
                outcome["phase"] = "PASSED"
                outcome["builder"] = builder_handoff(
                    task_id, repo, pr, head, "CONTINUE", [])

    outcome["loopx"] = _loopx_refresh(task_id, outcome["phase"], pr)
    return outcome


def _pr_json_full(repo: str, pr: int) -> Optional[dict]:
    import json as _json
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json",
             "reviewDecision,headRefOid,mergeable,state,reviews,updatedAt"],
            capture_output=True, text=True, check=True, timeout=30)
        return _json.loads(res.stdout)
    except Exception:
        return None


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
