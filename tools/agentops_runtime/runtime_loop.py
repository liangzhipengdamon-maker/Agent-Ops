#!/usr/bin/env python3
"""Thin AUTO/MANUAL runtime adapter.

AGE-44 invariant: there is exactly one executable positive authority channel.
AGE-45 invariant: active MANUAL lifecycle mutations are accepted only through
exact action-specific externally signed Product Owner authority.
"""

import dataclasses
import json
import os
import re
import subprocess
from typing import Optional

from . import linear_adapter, review_intake, relay_client, lifecycle_guard
from .task_intake import spec_from_linear, evaluate_checkpoint
from .review_intake import read_github_pr, read_pr_head


def _bridge_dir() -> str:
    return os.environ.get("AGENT_BRIDGE_DIR", ".agent-bridge")


def _resolve_mode() -> str:
    """Resolve the positive authority mode from process env.

    Projected by ``governloop_runtime._compat.configure_process``. Defaults
    to ``"signed"`` so legacy / direct ``agentops_runtime`` callers keep
    their existing semantics; the interactive_local fallback is opt-in.
    """
    m = os.environ.get("AGENTOPS_MODE", "").strip().lower()
    return m if m in ("signed", "interactive_local") else "signed"


def _verified_scope_policy(task_id: str, repo: str, head_sha: str,
                            mode: str = "signed") -> "ScopePolicy":
    from .scope_firewall import ScopePolicy
    try:
        from governloop_runtime.authority import (
            verify_authority, verify_task_scope,
        )
        verified = verify_authority(task_id, expected_repo=repo)
    except Exception as exc:
        verified = {"ok": False, "detail": f"authority verifier unavailable: {exc}"}
    if mode == "interactive_local" and not verified.get("ok"):
        try:
            ts = verify_task_scope(task_id, expected_repo=repo)
        except Exception as exc:
            ts = {"ok": False, "detail": f"task-scope verifier unavailable: {exc}"}
        if ts.get("ok"):
            verified = ts
    payload = verified.get("payload") or {} if verified.get("ok") else {}
    protected = tuple(r.strip() for r in
        os.environ.get("AGENTOPS_PROTECTED_REPOSITORIES", "").split(",") if r.strip())
    if not protected:
        protected = ("liangzhipengdamon-maker/LearnMind-English",
                     "liangzhipengdamon-maker/AI-Investment-Lab")
    # Head pin only comes from task-scope payload; caller head is the live
    # observed PR head and is not a pin. baseline_sha != head_sha is legal;
    # only an explicit payload.head_sha pin triggers drift detection in
    # ``evaluate_scope.head_exact``.
    head_pin = str(payload.get("head_sha") or "")
    return ScopePolicy(
        task_id=task_id, repository=repo,
        branch=str(payload.get("branch") or ""),
        base_sha=str(payload.get("baseline_sha") or ""), head_sha=head_pin,
        allowed_paths=tuple(payload.get("allowed_paths") or ()),
        allowed_operations=tuple(payload.get("allowed_operations") or ()),
        protected_repositories=protected, allowed_ready_merge_deploy=False,
        binding_ok=bool(
            verified.get("ok") and payload.get("repository") == repo
            and payload.get("branch") and payload.get("baseline_sha")
            and payload.get("allowed_paths") and payload.get("allowed_operations")),
        authoritative_changed_files=(),
    )


def _load_scope_policy(task_id: str, repo: str, observed_branch: str,
                       observed_base: str, head_sha: str, pr: str,
                       profile_path: Optional[str] = None) -> "ScopePolicy":
    """Parse the pre-v0.1 structural scope shape without granting authority."""
    from .scope_firewall import ScopePolicy
    del observed_branch, observed_base, pr
    prof = {}
    if profile_path and os.path.exists(profile_path):
        try:
            with open(profile_path) as f:
                prof = json.load(f)
        except (OSError, json.JSONDecodeError):
            prof = {}
    canonical_repo = os.environ.get("AGENTOPS_SCOPE_REPOSITORY", "").strip()
    expected_branch = os.environ.get("AGENTOPS_AUTHORIZED_BRANCH", "").strip()
    expected_base = os.environ.get("AGENTOPS_BASELINE_SHA", "").strip()
    allowed_ops = tuple(o.strip() for o in
        os.environ.get("AGENTOPS_AUTHORIZED_OPERATIONS", "").split(",") if o.strip())
    allowed_paths = tuple(p.strip() for p in
        os.environ.get("AGENTOPS_ALLOWED_PATHS", "").split(",") if p.strip())
    protected = tuple(r.strip() for r in
        os.environ.get("AGENTOPS_PROTECTED_REPOSITORIES", "").split(",") if r.strip())
    if not protected:
        protected = ("liangzhipengdamon-maker/LearnMind-English",
                     "liangzhipengdamon-maker/AI-Investment-Lab")
    lifecycle = {"ready", "merge", "close", "tag", "release", "deploy"}
    contains_lifecycle = any(op.lower() in lifecycle for op in allowed_ops)
    binding_ok = bool(canonical_repo and canonical_repo == repo
                      and expected_branch and expected_base and allowed_paths
                      and allowed_ops and not contains_lifecycle)
    return ScopePolicy(
        task_id=task_id, repository=repo, branch=expected_branch,
        base_sha=expected_base, head_sha=head_sha, allowed_paths=allowed_paths,
        allowed_operations=allowed_ops, protected_repositories=protected,
        allowed_ready_merge_deploy=False, binding_ok=binding_ok,
        authoritative_changed_files=tuple(
            prof.get("authoritative_changed_files") or ()),
    )


def builder_handoff(task_id: str, repo: str, pr: str, head: str,
                    phase: str, findings: list,
                    policy: Optional["ScopePolicy"] = None,
                    observed_branch: str = "",
                    observed_base: str = "",
                    mode: Optional[str] = None) -> dict:
    from .scope_firewall import evaluate_builder_wake, WorktreeState
    if mode is None:
        mode = _resolve_mode()
    if mode not in ("signed", "interactive_local"):
        mode = "signed"
    bd = _bridge_dir()
    if policy is None:
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd, "reason": "no scope policy bound for Builder wake"}
    verified_policy = _verified_scope_policy(task_id, repo, head, mode=mode)
    if not verified_policy.binding_ok:
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd,
                "reason": "external signed operator authority unavailable or invalid"}
    verified_policy = dataclasses.replace(
        verified_policy,
        changed_files_unreadable=getattr(policy, "changed_files_unreadable", False),
        authoritative_changed_files=getattr(policy, "authoritative_changed_files", ()),
    )
    policy = verified_policy
    origin_repo = _git_origin()
    if origin_repo:
        policy = dataclasses.replace(policy, origin_repo=origin_repo)
    else:
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd, "reason": "local git origin unverifiable; fail closed"}
    if getattr(policy, "changed_files_unreadable", False):
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd, "checks": {"changed_files_readable": False},
                "reason": "authoritative PR changed-file set could not be read"}
    try:
        cb = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True, timeout=15)
        st = subprocess.run(["git", "status", "--porcelain"],
                            capture_output=True, text=True, timeout=15)
        if cb.returncode != 0 or st.returncode != 0:
            raise OSError("git state unreadable")
        changed = [line[3:].strip() for line in (st.stdout or "").splitlines()
                   if len(line) > 3]
        wt = WorktreeState(cb.stdout.strip(), bool(st.stdout.strip()), tuple(changed))
    except Exception:
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd, "reason": "local git/worktree state unverifiable; fail closed"}
    operation = "continue" if phase == "CONTINUE" else (
        "complete" if phase == "COMPLETE" else "fix")
    verdict = evaluate_builder_wake(
        policy, task_id, repo, observed_branch, observed_base, head,
        operation=operation, target_paths=None, worktree=wt)
    if not verdict.get("ok"):
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd, "checks": verdict.get("checks"),
                "reason": verdict.get("reason")}
    try:
        os.makedirs(bd, exist_ok=True)
        with open(os.path.join(bd, "status.json"), "w") as f:
            json.dump({"protocol_version": "1", "state": phase, "repo": repo,
                       "pr": str(pr), "head": head, "request": "review"}, f, indent=2)
        with open(os.path.join(bd, "findings.md"), "w") as f:
            f.write("\n\n---\n\n".join(findings) if findings else "")
        return {"ok": True, "state": phase, "bridge": bd,
                "checks": verdict.get("checks")}
    except OSError as exc:
        return {"ok": False, "state": phase, "bridge": bd, "detail": str(exc)}


def _loopx_refresh(task_id: str, phase: str, pr: str) -> dict:
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
    except Exception as exc:
        return {"ok": False, "detail": f"loopx unavailable: {exc}"}


def _gate_status_report(task_id: str, repo: str, pr: str, head: str) -> dict:
    marker = os.path.join(_bridge_dir(), "gate_report.json")
    try:
        with open(marker) as f:
            data = json.load(f)
        if (data.get("repo") == repo and str(data.get("pr")) == str(pr)
                and data.get("head") == head and data.get("sent")
                and data.get("delivered")):
            return {"sent": True, "delivered": True, "duplicate": True,
                    "correlation_id": data.get("correlation_id")}
    except (OSError, json.JSONDecodeError):
        pass
    import uuid
    req_id = f"GATE_{uuid.uuid4().hex[:12]}"
    payload = (f"REVIEW_REQUEST_ID: {req_id}\nREPO: {repo}\nPR: {pr}\nHEAD: {head}\n"
               "REQUEST: status_report\nSTATE: WAITING_PO_AUTH\n"
               "SUMMARY: MANUAL checkpoint reached; waiting for PO decision\n"
               "UNAUTHORIZED_ACTIONS: NONE\n")
    out = relay_client.send_status_report(payload, "/tmp/agentops_runtime_report")
    delivered = out.get("delivered", False)
    try:
        os.makedirs(_bridge_dir(), exist_ok=True)
        with open(marker, "w") as f:
            json.dump({"repo": repo, "pr": str(pr), "head": head,
                       "sent": True, "delivered": delivered,
                       "correlation_id": out.get("correlation_id")}, f)
    except OSError:
        pass
    return {"sent": True, "delivered": delivered, "duplicate": False,
            "correlation_id": out.get("correlation_id")}


def _legacy_po_decision(task_id: str, repo: str, pr: str, head: str,
                        reviews: list) -> Optional[str]:
    """Historical structural parser; its output is not used by live authority."""
    del task_id, repo, pr
    trusted = review_intake.trusted_reviewers()
    for review in reviews or []:
        body = review.get("body") or ""
        if "PO_DECISION:" not in body:
            continue
        login = ((review.get("author") or {}).get("login") or "").strip()
        if login not in trusted:
            continue
        match = re.search(r"HEAD:\s*(\S+)", body)
        binds = bool(match and match.group(1).strip().lower() == head.lower())
        commit = (review.get("commit_id") or "").lower()
        if not commit:
            commit = ((review.get("commit") or {}).get("oid") or "").lower()
        binds = binds or bool(commit and commit == head.lower())
        if not binds:
            continue
        decision = re.search(r"PO_DECISION:\s*(\w+)", body)
        if decision:
            return decision.group(1).upper()
    return None


def _authenticated_po_decision(repo: str, pr: str, head: str) -> Optional[str]:
    """Executable PO decision path: verify-only external signed evidence."""
    decision = lifecycle_guard.read_po_decision(_bridge_dir(), repo, pr, head)
    if not decision:
        return None
    return str(decision.get("decision") or "").upper() or None


def _po_decision(*args) -> Optional[str]:
    """Compatibility seam with a strict live/legacy split.

    Three arguments (repo, pr, head) are the live path and verify external
    signed PO evidence. Five arguments preserve the historical parser solely
    for structural regression compatibility; `decide()` never calls that form.
    """
    if len(args) == 3:
        return _authenticated_po_decision(*args)
    if len(args) == 5:
        return _legacy_po_decision(*args)
    raise TypeError("_po_decision expects live (repo, pr, head) or legacy 5-arg form")


def _checkpoint_reached(spec, review) -> bool:
    return bool(spec.checkpoint and evaluate_checkpoint(spec.checkpoint) == "REVIEW_PASS"
                and review.decision == "PASS")


def _checkpoint_evaluable(spec) -> bool:
    return evaluate_checkpoint(spec.checkpoint) is not None


def _accepted_completion(repo: str, pr: str, head: str) -> bool:
    """Completion is external signed evidence, never a Builder bridge file."""
    try:
        from governloop_runtime.completion import verify_completion
        return bool(verify_completion(repo, str(pr), head).get("ok"))
    except Exception:
        return False


def _task_is_terminal(lin: Optional[dict]) -> bool:
    return bool(lin and (
        lin.get("state_type") in ("canceled", "completed")
        or lin.get("state_name") in ("Canceled", "Done")))


def decide(task_id: str, repo: str, pr: str) -> dict:
    spec = spec_from_linear(task_id)
    if spec is None:
        return {"phase": "BLOCKED", "review_decision": "LINEAR_UNREADABLE",
                "findings": [], "checkpoint_reached": False,
                "decision_request": "cannot read Linear task"}
    if not spec.mode:
        return {"phase": "BLOCKED", "review_decision": "MODE_MISSING",
                "findings": [], "checkpoint_reached": False,
                "decision_request": "specify Execution Mode AUTO|MANUAL"}

    # Propagate the resolved mode into apply_verified_authority — otherwise
    # the second authority projection silently defaults to ``signed`` and
    # resets the interactive_local fallback that ``_compat.configure_process``
    # opted into via AGENTOPS_MODE.
    mode = _resolve_mode()
    try:
        from governloop_runtime.authority import apply_verified_authority
        authority_status = apply_verified_authority(task_id, expected_repo=repo, mode=mode)
    except Exception as exc:
        try:
            from governloop_runtime.authority import clear_positive_process_authority
            clear_positive_process_authority()
        except Exception:
            pass
        authority_status = {"ok": False, "status": "BLOCKED",
                            "detail": f"authority verifier unavailable: {exc}"}

    lin = linear_adapter.read_linear_issue(task_id)
    if _task_is_terminal(lin):
        return {"mode": spec.mode, "phase": "TERMINAL",
                "review_decision": "INCOMPLETE", "findings": [],
                "checkpoint_reached": False,
                "authority": {"status": authority_status.get("status"),
                              "authority_id": authority_status.get("authority_id"),
                              "ok": bool(authority_status.get("ok"))},
                "loopx": _loopx_refresh(task_id, "TERMINAL", pr)}

    head = read_pr_head(repo, int(pr)) or ""
    gh_state = _pr_state(repo, int(pr))
    if gh_state is None:
        return {"mode": spec.mode, "phase": "BLOCKED",
                "review_decision": "UNREADABLE_REMOTE", "findings": [],
                "checkpoint_reached": False, "head": head,
                "authority": {"status": authority_status.get("status"),
                              "authority_id": authority_status.get("authority_id"),
                              "ok": bool(authority_status.get("ok"))},
                "loopx": _loopx_refresh(task_id, "BLOCKED", pr)}

    if gh_state.get("state") in ("MERGED", "CLOSED"):
        if spec.mode == "MANUAL":
            if not head:
                return {"mode": spec.mode, "phase": "BLOCKED",
                        "review_decision": "LIFECYCLE_HEAD_UNREADABLE",
                        "findings": [], "checkpoint_reached": True, "head": head,
                        "authority": {"status": authority_status.get("status"),
                                      "authority_id": authority_status.get("authority_id"),
                                      "ok": bool(authority_status.get("ok"))},
                        "decision_request": "active MANUAL terminal mutation cannot be exact-bound",
                        "loopx": _loopx_refresh(task_id, "BLOCKED", pr)}
            violation = lifecycle_guard.active_manual_terminal_violation(
                _bridge_dir(), repo, str(pr), head, gh_state.get("state"))
            if violation:
                return {"mode": spec.mode, "phase": "BLOCKED",
                        "review_decision": "LIFECYCLE_VIOLATION",
                        "findings": [], "checkpoint_reached": True, "head": head,
                        "authority": {"status": authority_status.get("status"),
                                      "authority_id": authority_status.get("authority_id"),
                                      "ok": bool(authority_status.get("ok"))},
                        "lifecycle_violation": violation,
                        "decision_request": "active MANUAL task was closed/merged without exact signed lifecycle authorization",
                        "loopx": _loopx_refresh(task_id, "BLOCKED", pr)}
        return {"mode": spec.mode, "phase": "TERMINAL",
                "review_decision": "INCOMPLETE", "findings": [],
                "checkpoint_reached": False, "head": head,
                "authority": {"status": authority_status.get("status"),
                              "authority_id": authority_status.get("authority_id"),
                              "ok": bool(authority_status.get("ok"))},
                "loopx": _loopx_refresh(task_id, "TERMINAL", pr)}

    review = read_github_pr(repo, int(pr), head)
    outcome = {"mode": spec.mode, "phase": "REVIEW",
               "review_decision": review.decision, "findings": review.findings,
               "checkpoint_reached": False, "head": head,
               "authority": {"status": authority_status.get("status"),
                             "authority_id": authority_status.get("authority_id"),
                             "ok": bool(authority_status.get("ok"))}}

    pr_json = _pr_json_full(repo, int(pr))
    observed_base = (pr_json or {}).get("baseRefOid") or ""
    observed_branch = (pr_json or {}).get("headRefName") or ""
    policy = _load_scope_policy(task_id, repo, observed_branch, observed_base, head, pr)
    changed = _pr_changed_files(repo, int(pr))
    policy = dataclasses.replace(
        policy, changed_files_unreadable=changed is None,
        authoritative_changed_files=tuple(changed or ()))

    if review.decision in ("CHANGES_REQUESTED", "NOT_PASS"):
        outcome["phase"] = "FIX"
        outcome["builder"] = builder_handoff(
            task_id, repo, pr, head, "BUILDER_FIXING", review.findings,
            policy=policy, observed_branch=observed_branch, observed_base=observed_base)
        _apply_builder_result(outcome)
    elif review.decision == "PASS":
        if spec.mode == "MANUAL":
            if not _checkpoint_evaluable(spec):
                outcome["phase"] = "BLOCKED"
                outcome["review_decision"] = "CHECKPOINT_UNEVALUABLE"
            elif _checkpoint_reached(spec, review):
                outcome["checkpoint_reached"] = True
                po = _po_decision(repo, pr, head)
                if po == "APPROVE":
                    if _accepted_completion(repo, pr, head):
                        outcome["phase"] = "COMPLETE"
                    else:
                        outcome["phase"] = "PASSED"
                        outcome["po_decision"] = "APPROVE"
                        outcome["builder"] = builder_handoff(
                            task_id, repo, pr, head, "CONTINUE", [], policy=policy,
                            observed_branch=observed_branch, observed_base=observed_base)
                        _apply_builder_result(outcome)
                elif po in ("REJECT", "CHANGES", "CHANGES_REQUESTED"):
                    outcome["phase"] = "FIX"
                    outcome["po_decision"] = po
                    outcome["builder"] = builder_handoff(
                        task_id, repo, pr, head, "BUILDER_FIXING",
                        [f"PO decision {po} at checkpoint {spec.checkpoint}"],
                        policy=policy, observed_branch=observed_branch,
                        observed_base=observed_base)
                    _apply_builder_result(outcome)
                else:
                    outcome["phase"] = "WAITING_PO_AUTH"
                    outcome["gate_report"] = _gate_status_report(task_id, repo, pr, head)
            else:
                outcome["phase"] = "PASSED"
                outcome["builder"] = builder_handoff(
                    task_id, repo, pr, head, "CONTINUE", [], policy=policy,
                    observed_branch=observed_branch, observed_base=observed_base)
                _apply_builder_result(outcome)
        else:
            if _accepted_completion(repo, pr, head):
                outcome["phase"] = "COMPLETE"
            else:
                outcome["phase"] = "PASSED"
                outcome["builder"] = builder_handoff(
                    task_id, repo, pr, head, "CONTINUE", [], policy=policy,
                    observed_branch=observed_branch, observed_base=observed_base)
                _apply_builder_result(outcome)
    outcome["loopx"] = _loopx_refresh(task_id, outcome["phase"], pr)
    return outcome


def _apply_builder_result(outcome: dict) -> None:
    builder = outcome.get("builder") or {}
    if builder.get("ok") is False and builder.get("blocked"):
        outcome["phase"] = "BLOCKED"
        outcome["review_decision"] = "SCOPE_BLOCKED"
        outcome["decision_request"] = (
            f"scope firewall blocked Builder wake: {builder.get('reason')}")


def _pr_json_full(repo: str, pr: int) -> Optional[dict]:
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo, "--json",
             "reviewDecision,headRefOid,mergeable,state,reviews,updatedAt,baseRefOid,headRefName"],
            capture_output=True, text=True, check=True, timeout=30)
        return json.loads(res.stdout)
    except Exception:
        return None


def _git_origin() -> Optional[str]:
    try:
        res = subprocess.run(["git", "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            return None
        url = res.stdout.strip()
        match = re.search(r"(?:github\.com[:/]|git@github\.com:)([^/\s]+/[^/\s]+?)(?:\.git)?$", url)
        return match.group(1) if match else url.rstrip("/")
    except Exception:
        return None


def _pr_changed_files(repo: str, pr: int) -> Optional[list]:
    try:
        res = subprocess.run(
            ["gh", "pr", "diff", str(pr), "--repo", repo, "--name-only"],
            capture_output=True, text=True, check=True, timeout=30)
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        return None


def _pr_state(repo: str, pr: int) -> Optional[dict]:
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo, "--json", "state"],
            capture_output=True, text=True, check=True, timeout=30)
        return json.loads(res.stdout)
    except Exception:
        return None
