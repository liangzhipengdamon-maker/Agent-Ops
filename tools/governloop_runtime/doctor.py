"""Read-only first-task readiness diagnostics for GovernLoop v0.1.

Doctor observes the current environment and existing positive authority. Signed
operator authority remains the preferred source. If it is absent, doctor may
reuse an already-recorded, independently verified interactive-local task scope
for diagnostics; doctor never creates or broadens either authority source.
It never creates authority, credentials, branches, PRs, or lifecycle decisions.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Optional

from . import authority, setup_wizard

_GITHUB_RE = re.compile(r"(?:github\.com[:/]|git@github\.com:)([^/\s]+/[^/\s]+?)(?:\.git)?$")
_NEXT_ACTION_ORDER = (
    "git_repository",
    "positive_authority",
    "git_branch",
    "baseline_commit",
    "baseline_history",
    "worktree_scope",
    "github_auth",
    "linear_task",
    "reviewer_binding",
    "pull_request",
)


def _run(args, timeout=20):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout.strip(), out.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def _check(name, status, detail, *, next_action=None, data=None):
    item = {"name": name, "status": status, "detail": detail}
    if next_action:
        item["next_action"] = next_action
    if data is not None:
        item["data"] = data
    return item


def _origin_repo(url):
    value = (url or "").strip().rstrip("/")
    match = _GITHUB_RE.search(value)
    return match.group(1).removesuffix(".git") if match else None


def _concise_command_error(err, fallback):
    """Return a short deterministic diagnostic, never a command usage dump."""
    text = (err or "").strip()
    if not text:
        return fallback
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        lower = line.lower()
        if "not a git repository" in lower:
            return "current directory is not a git worktree"
        if line.startswith("fatal:"):
            return line
    for line in lines:
        lower = line.lower()
        if line.startswith("-") or lower.startswith(("usage:", "or:", "git diff", "git rev-parse")):
            continue
        return line[:240]
    return fallback


def _path_allowed(path, allowed_paths):
    from agentops_runtime.scope_firewall import _is_path_allowed
    return _is_path_allowed(path, tuple(allowed_paths or ()))


def _git_worktree_available():
    rc, out, err = _run(["git", "rev-parse", "--is-inside-work-tree"])
    return rc == 0 and out.strip().lower() == "true", _concise_command_error(
        err, "current directory is not a git worktree")


def _changed_worktree_paths():
    paths, errors = [], []
    for command in (["git", "diff", "--name-only"],
                    ["git", "diff", "--cached", "--name-only"],
                    ["git", "ls-files", "--others", "--exclude-standard"]):
        rc, out, err = _run(command)
        if rc != 0:
            errors.append(_concise_command_error(err, "git worktree state unreadable"))
            continue
        for raw in out.splitlines():
            value = raw.strip()
            if value and value not in paths:
                paths.append(value)
    return paths, errors


def _worktree_scope_check(verified):
    payload = verified.get("payload") or {}
    allowed = payload.get("allowed_paths") if verified.get("ok") else None
    paths, errors = _changed_worktree_paths()
    if errors:
        return _check("worktree_scope", "BLOCKED",
                      "cannot determine complete worktree state: " + "; ".join(errors),
                      next_action="repair git/worktree readability; never assume unreadable changes are in scope")
    if not allowed:
        if paths:
            return _check("worktree_scope", "BLOCKED",
                          "worktree has changes but no verified allowed-path authority",
                          next_action="external operator must provision signed authority before Builder mutation",
                          data={"changed_paths": paths})
        return _check("worktree_scope", "PASS", "worktree clean", data={"changed_paths": []})
    outside = [p for p in paths if not _path_allowed(p, allowed)]
    if outside:
        return _check("worktree_scope", "BLOCKED",
                      "uncommitted paths outside operator-bound scope",
                      next_action="clean/stash unrelated changes or use an isolated worktree; do not broaden authority to absorb contamination",
                      data={"outside_paths": outside, "changed_paths": paths})
    return _check("worktree_scope", "PASS",
                  "worktree clean" if not paths else "all uncommitted paths are within bound scope",
                  data={"changed_paths": paths})


def _baseline_history_check(baseline):
    """Require the current HEAD to descend from the exact signed baseline."""
    rc, head, err = _run(["git", "rev-parse", "HEAD"])
    if rc != 0 or not head:
        return _check(
            "baseline_history", "BLOCKED",
            _concise_command_error(err, "current HEAD unreadable"),
            next_action="restore readable git history; never infer baseline ancestry")

    rc, _, err = _run(["git", "merge-base", "--is-ancestor", baseline, head])
    if rc == 0:
        return _check(
            "baseline_history", "PASS",
            f"current HEAD {head} descends from exact signed baseline {baseline}",
            data={"head": head, "baseline_sha": baseline})
    if rc == 1:
        return _check(
            "baseline_history", "BLOCKED",
            f"current HEAD {head} does not descend from exact signed baseline {baseline}",
            next_action="switch/recreate the authorized branch from the exact signed baseline; do not substitute another baseline",
            data={"head": head, "baseline_sha": baseline})
    return _check(
        "baseline_history", "BLOCKED",
        _concise_command_error(err, "cannot verify baseline ancestry"),
        next_action="repair/fetch git history until exact baseline ancestry can be verified",
        data={"head": head, "baseline_sha": baseline})


def _git_checks(repo, verified):
    available, detail = _git_worktree_available()
    if not available:
        action = f"clone/open the target repository `{repo}` and rerun doctor from that worktree"
        return [
            _check("git_repository", "BLOCKED", detail, next_action=action),
            _check("git_branch", "BLOCKED", "git branch unavailable until a target worktree is open", next_action=action),
            _check("baseline_commit", "BLOCKED", "baseline cannot be verified outside a target worktree", next_action=action),
            _check("baseline_history", "BLOCKED", "baseline ancestry cannot be verified outside a target worktree", next_action=action),
            _check("worktree_scope", "BLOCKED", "worktree scope cannot be verified outside a target worktree", next_action=action),
        ]

    checks = []
    rc, origin, err = _run(["git", "remote", "get-url", "origin"])
    observed = _origin_repo(origin) if rc == 0 else None
    if observed == repo:
        checks.append(_check("git_repository", "PASS", f"origin = {repo}"))
    else:
        checks.append(_check("git_repository", "BLOCKED",
                             f"expected {repo}; observed {observed or _concise_command_error(err, 'unreadable origin')}",
                             next_action="open the intended repository/worktree; do not rewrite authority to match the directory"))

    payload = verified.get("payload") or {}
    expected_branch = payload.get("branch") if verified.get("ok") else None
    rc, branch, err = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if rc != 0:
        checks.append(_check("git_branch", "BLOCKED", _concise_command_error(err, "current branch unreadable")))
    elif not expected_branch:
        checks.append(_check("git_branch", "BLOCKED", f"current branch = {branch}; no verified branch authority",
                             next_action="external operator must provision signed authority before Builder execution"))
    elif branch == expected_branch:
        checks.append(_check("git_branch", "PASS", f"branch = {branch}"))
    else:
        checks.append(_check("git_branch", "BLOCKED",
                             f"bound branch = {expected_branch}; current branch = {branch}",
                             next_action="switch to the exact operator-authorized branch; do not alter authority from Builder inference"))

    baseline = payload.get("baseline_sha") if verified.get("ok") else None
    if baseline:
        rc, _, _ = _run(["git", "cat-file", "-e", f"{baseline}^{{commit}}"])
        if rc == 0:
            checks.append(_check("baseline_commit", "PASS", f"bound baseline exists: {baseline}"))
            checks.append(_baseline_history_check(baseline))
        else:
            checks.append(_check("baseline_commit", "BLOCKED",
                                 f"bound baseline not present locally: {baseline}",
                                 next_action="fetch repository history; never substitute another baseline"))
            checks.append(_check("baseline_history", "BLOCKED",
                                 "baseline ancestry cannot be verified because the signed baseline is unavailable",
                                 next_action="fetch the exact signed baseline before Builder execution"))
    else:
        checks.append(_check("baseline_commit", "BLOCKED", "no verified baseline authority",
                             next_action="external operator must provision an exact baseline SHA"))
        checks.append(_check("baseline_history", "BLOCKED", "no verified baseline authority",
                             next_action="external operator must provision an exact baseline SHA"))
    checks.append(_worktree_scope_check(verified))
    return checks


def _github_auth_check():
    rc, out, err = _run(["gh", "auth", "status"], timeout=30)
    if rc == 0:
        return _check("github_auth", "PASS", "GitHub CLI authentication available")
    return _check("github_auth", "BLOCKED", _concise_command_error(err or out, "GitHub CLI authentication unavailable"),
                  next_action="authenticate GitHub CLI for the target repository")


def _linear_check(task_id):
    if not os.environ.get("LINEAR_ACCESS_TOKEN", "").strip():
        return _check("linear_task", "BLOCKED", "LINEAR_ACCESS_TOKEN is not present",
                      next_action="provide LINEAR_ACCESS_TOKEN in the controller environment; do not reconstruct task instructions"), None
    try:
        from agentops_runtime.linear_adapter import read_linear_issue
        from agentops_runtime.task_intake import parse_mode, extract_checkpoint
        issue = read_linear_issue(task_id)
    except Exception as exc:
        return _check("linear_task", "BLOCKED", f"Linear task read failed: {exc}"), None
    if not issue:
        return _check("linear_task", "BLOCKED", f"task {task_id} is unreadable/not found",
                      next_action="verify token access and task identifier"), None
    description = issue.get("description") or ""
    mode = parse_mode(description)
    if mode not in ("AUTO", "MANUAL"):
        return _check("linear_task", "BLOCKED", "Execution Mode is missing/ambiguous",
                      next_action="Product Owner must set exactly one Execution Mode: AUTO or MANUAL"), issue
    data = {"mode": mode, "state": issue.get("state_name")}
    if mode == "MANUAL":
        data["checkpoint"] = extract_checkpoint(description)
    return _check("linear_task", "PASS", f"task {task_id} readable", data=data), issue


def _reviewer_check(repo, *, probe):
    try:
        config = setup_wizard.load_config()
    except Exception as exc:
        return _check("reviewer_binding", "BLOCKED", f"reviewer config unreadable: {exc}",
                      next_action=f"run `governloop setup --repo {repo}`")
    route = (config.get("routes") or {}).get(repo)
    runtime = config.get("runtime") or {}
    if not isinstance(route, dict):
        return _check("reviewer_binding", "BLOCKED", f"no reviewer route is bound for {repo}",
                      next_action=f"run `governloop setup --repo {repo}`")
    try:
        url = setup_wizard.normalize_conversation_url(route.get("conversation_url"))
        port = setup_wizard.normalize_cdp_port(route.get("cdp_port") or runtime.get("cdp_port"))
    except Exception as exc:
        return _check("reviewer_binding", "BLOCKED", f"reviewer route is invalid: {exc}")
    if not probe:
        return _check("reviewer_binding", "PASS", f"reviewer configured on CDP {port}",
                      data={"conversation_url": url, "cdp_port": port})
    result = setup_wizard.test_connection(url, port)
    if result.get("ok"):
        return _check("reviewer_binding", "PASS", f"dedicated reviewer reachable on CDP {port}")
    return _check("reviewer_binding", "BLOCKED",
                  result.get("error") or result.get("detail") or "reviewer connection test failed",
                  next_action="open exactly one bound ChatGPT conversation tab in the configured GovernLoop Chrome runtime")


def _pr_check(repo, pr: Optional[str], verified):
    payload = verified.get("payload") or {}
    if not pr:
        branch = payload.get("branch") or "<authorized-branch>"
        return _check("pull_request", "EXPECTED_GATE",
                      "no PR supplied; this is valid during first-task bootstrap",
                      next_action=f"after bounded work is pushed on `{branch}`, create a Draft PR to the authorized baseline/base; then rerun doctor --pr <number>. Draft creation grants no Ready/Merge authority")
    rc, out, err = _run(["gh", "pr", "view", str(pr), "--repo", repo, "--json",
                         "number,state,isDraft,headRefName,headRefOid,baseRefOid,baseRefName"], timeout=30)
    if rc != 0:
        return _check("pull_request", "BLOCKED", _concise_command_error(err or out, f"PR {pr} unreadable"),
                      next_action="verify the exact PR/repository; never substitute another PR")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return _check("pull_request", "BLOCKED", "GitHub PR response invalid")
    if data.get("state") != "OPEN":
        return _check("pull_request", "BLOCKED", f"PR {pr} state = {data.get('state')}", data=data)
    if not verified.get("ok"):
        return _check("pull_request", "BLOCKED", "PR readable but positive authority is not verified",
                      next_action="external operator must provision signed authority before the PR becomes controlled", data=data)
    mismatches = []
    if data.get("headRefName") != payload.get("branch"):
        mismatches.append(f"head branch {data.get('headRefName')} != authority {payload.get('branch')}")
    if data.get("baseRefOid") != payload.get("baseline_sha"):
        mismatches.append(f"base {data.get('baseRefOid')} != authority baseline {payload.get('baseline_sha')}")
    if mismatches:
        return _check("pull_request", "BLOCKED", "; ".join(mismatches), data=data)
    allowed = payload.get("allowed_paths") or []
    rc, names, err = _run(["gh", "pr", "diff", str(pr), "--repo", repo, "--name-only"], timeout=30)
    if rc != 0:
        return _check("pull_request", "BLOCKED", _concise_command_error(err, "PR changed-file list unreadable"),
                      next_action="restore GitHub evidence readability; never assume unreadable files are in scope", data=data)
    changed = [line.strip() for line in names.splitlines() if line.strip()]
    outside = [p for p in changed if not _path_allowed(p, allowed)]
    if outside:
        return _check("pull_request", "BLOCKED", "PR contains changed files outside operator-bound paths",
                      next_action="remove out-of-scope changes; do not broaden authority to absorb them",
                      data={**data, "changed_files": changed, "outside_paths": outside})
    return _check("pull_request", "PASS",
                  f"PR #{pr} is {'Draft' if data.get('isDraft') else 'open'}; branch/baseline/files match bound scope",
                  data={**data, "changed_files": changed})


def _is_external_action(check):
    if check.get("name") == "positive_authority":
        return True
    if check.get("name") == "linear_task" and "Execution Mode" in check.get("detail", ""):
        return True
    return False


def _fallback_next_action(check):
    name = check.get("name") or "unknown"
    return (
        f"resolve the blocked prerequisite `{name}` using its diagnostic detail, then rerun doctor; "
        "do not skip to a later gate or broaden authority"
    )


def _select_next_action(checks):
    """Return an action for the earliest unsatisfied gate, never a later one."""
    by_name = {check.get("name"): check for check in checks}
    for name in _NEXT_ACTION_ORDER:
        check = by_name.get(name)
        if not check or check.get("status") not in ("BLOCKED", "EXPECTED_GATE"):
            continue
        action = check.get("next_action") or _fallback_next_action(check)
        key = "next_required_external_action" if _is_external_action(check) else "next_required_action"
        return key, {"check": name, "action": action}
    return None, None


def _resolve_positive_authority(task_id, repo):
    """Prefer signed authority, then reuse an already-verified task scope.

    This is diagnostic-only. It does not create a task scope, mutate process
    authority, or change runtime mode. A task-scope fallback is considered only
    when signed authority is unavailable and only through the existing verifier.
    """
    signed = authority.verify_authority(task_id, expected_repo=repo)
    if signed.get("ok"):
        return signed, "signed", signed
    task_scope = authority.verify_task_scope(task_id, expected_repo=repo)
    if task_scope.get("ok"):
        return task_scope, "interactive_local", signed
    return signed, "signed", signed


def run_doctor(task_id, repo, pr=None, *, probe_reviewer=True):
    verified, authority_source, signed_attempt = _resolve_positive_authority(task_id, repo)
    checks = []
    if verified.get("ok"):
        payload = verified.get("payload") or {}
        if authority_source == "interactive_local":
            detail = f"interactive-local task scope verified: {verified.get('authority_id')}"
        else:
            detail = f"external signed authority verified: {verified.get('authority_id')}"
        checks.append(_check("positive_authority", "PASS", detail,
                             data={"authority_source": authority_source,
                                   "authority_id": verified.get("authority_id"),
                                   "repository": payload.get("repository"),
                                   "branch": payload.get("branch"),
                                   "baseline_sha": payload.get("baseline_sha"),
                                   "allowed_paths": payload.get("allowed_paths"),
                                   "allowed_operations": payload.get("allowed_operations"),
                                   "trusted_reviewers": payload.get("trusted_reviewers")}))
    else:
        detail = signed_attempt.get("detail") or "positive authority unavailable"
        ignored = signed_attempt.get("ignored_process_authority_fields") or []
        if ignored:
            detail += "; ignored raw process fields: " + ", ".join(ignored)
        checks.append(_check("positive_authority", "BLOCKED", detail,
                             next_action="external operator must provision a valid signed authority document through the OS-protected control channel; runtime/Builder cannot mint it"))
    checks.extend(_git_checks(repo, verified))
    checks.append(_github_auth_check())
    linear, _ = _linear_check(task_id)
    checks.append(linear)
    checks.append(_reviewer_check(repo, probe=probe_reviewer))
    checks.append(_pr_check(repo, pr, verified))
    status = "BLOCKED" if any(c["status"] == "BLOCKED" for c in checks) else (
        "BOOTSTRAP_REQUIRED" if any(c["status"] == "EXPECTED_GATE" for c in checks) else "READY")
    result = {"tool": "GovernLoop Doctor", "task_id": task_id, "repo": repo,
              "pr": str(pr) if pr else None, "status": status, "checks": checks,
              "authority_source": authority_source if verified.get("ok") else None,
              "mutations_performed": False}
    key, next_action = _select_next_action(checks)
    if key:
        result[key] = next_action
    return result