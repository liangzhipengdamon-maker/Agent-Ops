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

import dataclasses
import json
import os
import re
import subprocess
import time
from typing import Optional

from . import linear_adapter
from . import review_intake
from .task_intake import spec_from_linear, evaluate_checkpoint
from .review_intake import read_github_pr, read_pr_head
from . import relay_client


def _bridge_dir() -> str:
    return os.environ.get("AGENT_BRIDGE_DIR", ".agent-bridge")


def _load_scope_policy(task_id: str, repo: str, observed_branch: str,
                       observed_base: str, head_sha: str, pr: str,
                       profile_path: Optional[str] = None) -> "ScopePolicy":
    """Build the immutable scope policy for one episode from an INDEPENDENT,
    authoritative project profile + the explicit invocation context. The
    policy is NEVER derived from runtime state, review verdicts, Builder
    findings, or prompt text.

    P0-1: expected branch and baseline come from the profile's
    `canonical_branch` and `baseline_sha` (authoritative project/task scope),
    NOT from the PR's own headRefName/baseRefOid. The PR-observed branch and
    base are only compared against these expected values for drift detection,
    so a PR cannot self-certify its own branch/base.

    The invocation `repo` must exactly equal the profile's canonical
    repository (project identity); otherwise binding_ok=False and the
    firewall fails closed.

    Allowed paths default to the explicit controlled directories (NO implicit
    '.'); operations default to fix/continue/complete. Ready/Merge/Deploy are
    excluded unless a profile explicitly authorizes them.
    """
    from .scope_firewall import ScopePolicy

    if profile_path is None:
        # Resolve the authoritative project profile from the repo root.
        import pathlib
        here = pathlib.Path(__file__).resolve().parent
        for base in (pathlib.Path.cwd(), here, here.parent, here.parent.parent,
                     here.parent.parent.parent):
            cand = base / "profiles" / "agentops.json"
            if cand.exists():
                profile_path = str(cand)
                break

    prof = {}
    if profile_path and os.path.exists(profile_path):
        try:
            with open(profile_path) as f:
                prof = json.load(f)
        except (OSError, json.JSONDecodeError):
            prof = {}

    github = prof.get("github") or {}

    # R5-P0-1: ALL authorization-bearing fields come from ONE immutable,
    # out-of-episode source (env established before execution). NO
    # mutable-worktree fallback for authorization fields. The profile is used
    # ONLY for non-authorization identity (project name / repo) and even the
    # repo identity is verified against the local origin at wake time, so a
    # Builder cannot broaden its own authorization.
    canonical_repo = (os.environ.get("AGENTOPS_SCOPE_REPOSITORY", "").strip()
                      or github.get("repository") or "")
    expected_branch = os.environ.get("AGENTOPS_AUTHORIZED_BRANCH", "").strip()
    expected_base = os.environ.get("AGENTOPS_BASELINE_SHA", "").strip()
    env_ops = [o.strip() for o in
               os.environ.get("AGENTOPS_AUTHORIZED_OPERATIONS", "").split(",")
               if o.strip()]
    allowed_ops = tuple(env_ops or ["fix", "continue", "complete"])
    env_paths = [p.strip() for p in
                 os.environ.get("AGENTOPS_ALLOWED_PATHS", "").split(",")
                 if p.strip()]
    allowed_paths = tuple(env_paths or ["tools/agentops_runtime/",
                                        "scripts/", "docs/", "tests/"])
    env_protected = [r.strip() for r in
                     os.environ.get("AGENTOPS_PROTECTED_REPOSITORIES",
                                    "").split(",") if r.strip()]
    protected = tuple(env_protected
                      or ["liangzhipengdamon-maker/LearnMind-English",
                          "liangzhipengdamon-maker/AI-Investment-Lab"])
    allow_rmd = os.environ.get("AGENTOPS_ALLOW_READY_MERGE_DEPLOY",
                               "").strip().lower() in ("1", "true", "yes")

    binding_ok = bool(canonical_repo) and canonical_repo == repo
    if not (expected_branch and expected_base):
        binding_ok = False  # no out-of-episode authority bound
    auth_changed = tuple(prof.get("authoritative_changed_files") or ())

    return ScopePolicy(
        task_id=task_id,
        repository=repo,
        branch=expected_branch,
        base_sha=expected_base,
        head_sha=head_sha,
        allowed_paths=allowed_paths,
        allowed_operations=allowed_ops,
        protected_repositories=protected,
        allowed_ready_merge_deploy=allow_rmd,
        binding_ok=binding_ok,
        authoritative_changed_files=auth_changed,
    )


def builder_handoff(task_id: str, repo: str, pr: str, head: str,
                    phase: str, findings: list,
                    policy: Optional["ScopePolicy"] = None,
                    observed_branch: str = "",
                    observed_base: str = "") -> dict:
    """Wake the existing Builder execution chain via the `.agent-bridge`
    protocol (status.json + findings.md). This is the established Builder
    handoff (AGENT_RUNNER_PROMPT.md); the runtime does not re-implement a
    Builder, it hands findings to the existing one.

    AGE-6: this is the MANDATORY scope/action firewall gate. A Builder wake
    is executable ONLY when the bound ScopePolicy passes for this exact
    repo/branch/base/head/operation. On failure NO status.json/findings.md
    is written (no executable wake) and the outcome is {ok: False,
    blocked: True, reason}. Fail-closed: any I/O error also returns
    ok=False."""
    from .scope_firewall import evaluate_builder_wake, WorktreeState

    bd = _bridge_dir()
    if policy is None:
        # No policy bound -> fail closed (never an implicit green light).
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd,
                "reason": "no scope policy bound for Builder wake"}

    # P0-1 (local origin): bind the policy to the actual local git origin.
    origin_repo = _git_origin()
    if origin_repo:
        policy = dataclasses.replace(policy, origin_repo=origin_repo)
    else:
        # Origin unverifiable -> fail closed (never skip origin binding).
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd,
                "reason": "local git origin unverifiable; fail closed"}

    # P0-2: if the authoritative changed-file retrieval failed, mark the
    # policy so the firewall blocks (never treat as zero changes).
    if getattr(policy, "changed_files_unreadable", False):
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd, "checks": {"changed_files_readable": False},
                "reason": ("authoritative PR changed-file set could not be "
                           "read; fail closed, no Builder wake")}

    # Clean-worktree contamination: observe current branch + uncommitted
    # changes (all changed paths must be inside the policy's allowed paths).
    # P0-3: an unverifiable local worktree (exception) must BLOCK, never skip.
    wt = None
    try:
        cb = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True, timeout=15)
        if cb.returncode != 0:
            return {"ok": False, "blocked": True, "state": phase,
                    "bridge": bd,
                    "reason": "git rev-parse HEAD unverifiable; fail closed"}
        cur_branch = cb.stdout.strip()
        st = subprocess.run(["git", "status", "--porcelain"],
                            capture_output=True, text=True, timeout=15)
        if st.returncode != 0:
            return {"ok": False, "blocked": True, "state": phase,
                    "bridge": bd,
                    "reason": "git status unverifiable; fail closed"}
        changed = []
        for line in (st.stdout or "").splitlines():
            if len(line) > 3:
                changed.append(line[3:].strip())
        wt = WorktreeState(current_branch=cur_branch,
                           has_uncommitted_changes=bool(st.stdout.strip()),
                           changed_paths=tuple(changed))
    except Exception:
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd,
                "reason": "local git/worktree state unverifiable; fail closed"}

    operation = "fix"
    if phase == "CONTINUE":
        operation = "continue"
    elif phase == "COMPLETE":
        operation = "complete"

    verdict = evaluate_builder_wake(
        policy, task_id, repo, observed_branch, observed_base, head,
        operation=operation, target_paths=None, worktree=wt)
    if not verdict.get("ok"):
        return {"ok": False, "blocked": True, "state": phase,
                "bridge": bd, "checks": verdict.get("checks"),
                "reason": verdict.get("reason")}

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
        return {"ok": True, "state": phase, "bridge": bd,
                "checks": verdict.get("checks")}
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


def _gate_status_report(task_id: str, repo: str, pr: str, head: str) -> dict:
    """Auto-send ONE Gate status_report via the existing Neutral Relay when
    the loop enters WAITING_PO_AUTH (MANUAL checkpoint reached). Fail-closed:
    `delivered` is true only when the exact 5-line ACK envelope binds the
    same REVIEW_REQUEST_ID/REPO/PR/HEAD. Uses the existing relay_client;
    never a manual copy/paste bypass.

    R8-1 retry semantics:
    - dedupe ONLY after a confirmed delivery (delivered=true) for this exact
      PR+HEAD (bridge `gate_report.json` marker);
    - delivered=false does NOT dedupe: the next watcher cycle must retry, and
      the marker is overwritten with the latest attempt so retry never
      suppresses resend.
    """
    marker = os.path.join(_bridge_dir(), "gate_report.json")
    try:
        with open(marker) as f:
            d = json.load(f)
        if (d.get("repo") == repo and str(d.get("pr")) == str(pr)
                and d.get("head") == head and d.get("sent")
                and d.get("delivered")):
            return {"sent": True, "delivered": True, "duplicate": True,
                    "correlation_id": d.get("correlation_id")}
    except (OSError, json.JSONDecodeError):
        pass
    import uuid
    req_id = f"GATE_{uuid.uuid4().hex[:12]}"
    payload = (f"REVIEW_REQUEST_ID: {req_id}\n"
               f"REPO: {repo}\n"
               f"PR: {pr}\n"
               f"HEAD: {head}\n"
               f"REQUEST: status_report\n"
               f"STATE: WAITING_PO_AUTH\n"
               f"SUMMARY: MANUAL checkpoint reached; waiting for PO decision\n"
               f"UNAUTHORIZED_ACTIONS: NONE\n")
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
    return {"sent": True, "delivered": delivered,
            "duplicate": False,
            "correlation_id": out.get("correlation_id")}


def _po_decision(task_id: str, repo: str, pr: str, head: str,
                 reviews: list) -> Optional[str]:
    """PO decision intake at a MANUAL checkpoint. The decision is a formal
    review at the exact current HEAD from a TRUSTED author carrying
    `PO_DECISION: <APPROVE|REJECT|CHANGES>` or a `po_decision.json` bridge
    file. Returns None when no decision for this exact PR+HEAD exists (loop
    stays in WAITING_PO_AUTH). R6-P0-1: untrusted author -> ignored."""
    for r in reviews or []:
        body = r.get("body") or ""
        if "PO_DECISION:" not in body:
            continue
        login = ((r.get("author") or {}).get("login") or "").strip()
        trusted = login and login in review_intake.trusted_reviewers()
        if not trusted:
            continue  # untrusted identity cannot inject a PO decision
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

    # AGE-6: bind the deterministic scope policy for this episode. Branch and
    # base come from the authoritative project profile (canonical_branch +
    # baseline_sha), NEVER from runtime state / review text / Builder
    # findings / the PR's own headRefName/baseRefOid (P0-1: no self-binding).
    observed_base = (pr_json or {}).get("baseRefOid") or ""
    observed_branch = (pr_json or {}).get("headRefName") or ""
    policy = _load_scope_policy(task_id, repo, observed_branch,
                                observed_base, head, pr)
    # P0-2: authoritative changed-file set from the real PR diff vs base.
    auth_changed = _pr_changed_files(repo, int(pr))
    if auth_changed is None:
        policy = dataclasses.replace(policy, changed_files_unreadable=True)
    else:
        policy = dataclasses.replace(
            policy, authoritative_changed_files=tuple(auth_changed))

    if review.decision in ("CHANGES_REQUESTED", "NOT_PASS"):
        outcome["phase"] = "FIX"          # findings -> Builder execution chain
        outcome["builder"] = builder_handoff(
            task_id, repo, pr, head, "BUILDER_FIXING", review.findings,
            policy=policy,
                            observed_branch=observed_branch,
                            observed_base=observed_base)
        _apply_builder_result(outcome)
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
                            task_id, repo, pr, head, "CONTINUE", [],
                            policy=policy,
                            observed_branch=observed_branch,
                            observed_base=observed_base)
                        _apply_builder_result(outcome)
                elif po in ("REJECT", "CHANGES", "CHANGES_REQUESTED"):
                    outcome["phase"] = "FIX"
                    outcome["po_decision"] = po
                    outcome["builder"] = builder_handoff(
                        task_id, repo, pr, head, "BUILDER_FIXING",
                        [f"PO decision {po} at checkpoint "
                         f"{spec.checkpoint}"], policy=policy,
                            observed_branch=observed_branch,
                            observed_base=observed_base)
                    _apply_builder_result(outcome)
                else:
                    outcome["phase"] = "WAITING_PO_AUTH"
                    outcome["gate_report"] = _gate_status_report(
                        task_id, repo, pr, head)
            else:
                outcome["phase"] = "PASSED"  # checkpoint not reached; continue
                outcome["builder"] = builder_handoff(
                    task_id, repo, pr, head, "CONTINUE", [],
                    policy=policy,
                            observed_branch=observed_branch,
                            observed_base=observed_base)
                _apply_builder_result(outcome)
        else:
            # P0-1: AUTO PASS wakes the Builder to continue in scope; accepted
            # completion is derived from evidence, not a bare PASS.
            if _accepted_completion(repo, pr, head):
                outcome["phase"] = "COMPLETE"
            else:
                outcome["phase"] = "PASSED"
                outcome["builder"] = builder_handoff(
                    task_id, repo, pr, head, "CONTINUE", [],
                    policy=policy,
                            observed_branch=observed_branch,
                            observed_base=observed_base)
                _apply_builder_result(outcome)

    outcome["loopx"] = _loopx_refresh(task_id, outcome["phase"], pr)
    return outcome


def _apply_builder_result(outcome: dict) -> None:
    """P0-3: when the firewall blocks a Builder wake, the runtime phase must
    become BLOCKED (AGE-6 requires a fail-closed outcome), never FIX/PASSED
    with an executable-looking continue."""
    builder = outcome.get("builder") or {}
    if builder.get("ok") is False and builder.get("blocked"):
        outcome["phase"] = "BLOCKED"
        outcome["review_decision"] = "SCOPE_BLOCKED"
        outcome["decision_request"] = (
            f"scope firewall blocked Builder wake: {builder.get('reason')}")


def _pr_json_full(repo: str, pr: int) -> Optional[dict]:
    import json as _json
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json",
             "reviewDecision,headRefOid,mergeable,state,reviews,updatedAt,"
             "baseRefOid,headRefName"],
            capture_output=True, text=True, check=True, timeout=30)
        return _json.loads(res.stdout)
    except Exception:
        return None


def _git_origin() -> Optional[str]:
    """Local git origin URL -> canonical owner/repo, or None if unreadable."""
    try:
        res = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            return None
        url = res.stdout.strip()
        # Accept ssh/git@/https forms -> owner/repo (strip .git).
        m = re.search(r"(?:github\.com[:/]|git@github\.com:)([^/\s]+/[^/\s]+?)(?:\.git)?$", url)
        return m.group(1) if m else url.rstrip("/")
    except Exception:
        return None


def _pr_changed_files(repo: str, pr: int) -> Optional[list]:
    """Authoritative changed-file set for a PR (vs its base), via gh."""
    try:
        res = subprocess.run(
            ["gh", "pr", "diff", str(pr), "--repo", repo, "--name-only"],
            capture_output=True, text=True, check=True, timeout=30)
        return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
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
