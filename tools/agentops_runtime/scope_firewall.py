#!/usr/bin/env python3
"""AGE-6 deterministic Scope & Action Firewall.

Thin fail-closed firewall integrated at the existing Builder handoff
boundary (`runtime_loop.builder_handoff`). It reuses the AGE-5
`scripts.auth_verifier` path rules where applicable and adds the missing
deterministic project/worktree/scope boundary. No second runtime, no new
Runner/scheduler/risk router/agent adapter.

Every check fails closed. `evaluate_scope` returns {ok, checks, reason}
where `checks` maps each check name to a bool and `ok` is the conjunction.
A failed scope produces NO executable Builder wake: the caller must not
emit `status.json`/`findings.md`, and must surface an explicit BLOCKED
outcome.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Iterable, Optional, Tuple


# Actions that are NEVER implied by a Builder wake / review PASS / ACK / CI /
# runtime state. They require a separate, explicit, action-specific
# authorization outside the runtime's scope policy.
LIFECYCLE_ACTIONS = ("ready", "merge", "deploy")


@dataclasses.dataclass(frozen=True)
class ScopePolicy:
    """Immutable, explicit scope for one controlled episode.

    All fields are exact-binding constraints. A policy is never derived from
    runtime state, review verdicts, Builder findings, or prompt text.
    """

    task_id: str
    repository: str
    branch: str
    base_sha: str
    head_sha: Optional[str] = None
    allowed_paths: Tuple[str, ...] = dataclasses.field(default_factory=tuple)
    allowed_operations: Tuple[str, ...] = dataclasses.field(
        default_factory=lambda: ("fix", "continue", "complete"))
    protected_repositories: Tuple[str, ...] = dataclasses.field(
        default_factory=tuple)
    allowed_ready_merge_deploy: bool = False
    binding_ok: bool = True
    authoritative_changed_files: Tuple[str, ...] = dataclasses.field(
        default_factory=tuple)
    changed_files_unreadable: bool = False
    origin_repo: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class ActionScope:
    """The concrete scope an action actually proposes to operate on."""

    task_id: str
    repository: str
    branch: str
    base_sha: str
    head_sha: Optional[str] = None
    target_paths: Tuple[str, ...] = dataclasses.field(default_factory=tuple)
    operation: str = "fix"


@dataclasses.dataclass(frozen=True)
class WorktreeState:
    """Observed local worktree facts used for contamination detection."""

    current_branch: str
    has_uncommitted_changes: bool = False
    changed_paths: Tuple[str, ...] = dataclasses.field(default_factory=tuple)


def _norm(path: str) -> str:
    return os.path.normpath(path or ".")


def _is_path_allowed(path: str, allowed: Iterable[str]) -> bool:
    """Strict path boundary with one explicit external-path exception.

    Relative paths keep the existing repository-scoped semantics. An absolute
    path is allowed only when the already-signed ``allowed_paths`` explicitly
    contains a canonical physical absolute root that contains the target. This
    keeps repo-external access task-bound without introducing a second authority
    schema or operator path.
    """
    raw = path or "."
    normalized = _norm(raw)

    # Preserve the existing fail-closed traversal rule, and also inspect the
    # raw spelling because normpath would otherwise erase ``..`` components.
    if ".." in raw.split(os.sep) or ".." in normalized.split(os.sep):
        return False

    if os.path.isabs(raw):
        target = os.path.realpath(raw)
        for a in allowed:
            if not a or not os.path.isabs(a):
                continue
            if ".." in a.split(os.sep):
                continue
            signed_root = os.path.normpath(a)
            root = os.path.realpath(a)
            # The signed entry itself must already name the physical canonical
            # root. A symlink alias could otherwise be retargeted after signing
            # and silently move positive authority to another directory.
            if signed_root != root:
                continue
            # Never turn an explicit external-path allowance into whole-disk
            # authority. Wider roots can be added deliberately in a future
            # policy if a real use case requires them.
            if root == os.path.abspath(os.sep):
                continue
            if target == root or target.startswith(root.rstrip(os.sep) + os.sep):
                return True
        return False

    for a in allowed:
        if os.path.isabs(a):
            continue
        norm_a = _norm(a)
        if norm_a == ".":
            return True  # explicit whole-repo boundary
        if normalized == norm_a:
            return True
        prefix = norm_a if norm_a.endswith(os.sep) else norm_a + os.sep
        if normalized.startswith(prefix):
            return True
    return False


def _is_protected(path: str, protected: Iterable[str]) -> bool:
    """A path inside a protected repository boundary is always rejected."""
    normalized = _norm(path)
    for p in protected:
        if normalized == _norm(p) or normalized.startswith(_norm(p) + os.sep):
            return True
    return False


def evaluate_scope(policy: ScopePolicy, action: ActionScope,
                   worktree: Optional[WorktreeState] = None) -> dict:
    """Evaluate an ActionScope against the ScopePolicy. Fail closed."""
    checks: dict = {}
    reason = None

    # 1. Project / repository exact binding.
    checks["binding_ok"] = policy.binding_ok
    if not checks["binding_ok"]:
        reason = ("policy not bound to an independent authoritative "
                  "project profile (canonical repository mismatch)")

    checks["repository_exact"] = (
        action.repository == policy.repository
        and bool(action.repository))
    if not checks["repository_exact"]:
        reason = (f"repository {action.repository!r} != policy "
                  f"{policy.repository!r}")

    # 1b. Protected repositories: AgentOps must never target a protected repo
    #     unless a separately scoped profile/policy for that repo is bound.
    checks["not_protected_repository"] = (
        action.repository not in policy.protected_repositories)
    if not checks["not_protected_repository"]:
        reason = (f"repository {action.repository!r} is protected; no "
                  f"separately scoped policy is bound")

    # 2. Branch exact binding.
    checks["branch_exact"] = bool(action.branch) and action.branch == policy.branch
    if not checks["branch_exact"]:
        reason = (f"branch {action.branch!r} != policy {policy.branch!r}")

    # 3. Exact baseline (base SHA) binding.
    checks["base_sha_exact"] = (
        bool(action.base_sha) and action.base_sha == policy.base_sha)
    if not checks["base_sha_exact"]:
        reason = (f"base_sha {action.base_sha!r} != policy {policy.base_sha!r}")

    # 3b. Exact target HEAD binding when the policy pins a head.
    checks["head_exact"] = True
    if policy.head_sha and action.head_sha != policy.head_sha:
        checks["head_exact"] = False
        reason = (f"head_sha {action.head_sha!r} != policy {policy.head_sha!r}")

    # 4. Path boundary + traversal/absolute/wildcard/protected rejection.
    checks["paths_allowed"] = bool(action.target_paths)
    for p in action.target_paths:
        if _is_protected(p, policy.protected_repositories):
            checks["paths_allowed"] = False
            reason = f"path {p!r} is a protected path"
            break
        if not _is_path_allowed(p, policy.allowed_paths):
            checks["paths_allowed"] = False
            reason = f"path {p!r} outside allowed paths {policy.allowed_paths!r}"
            break

    # 5. Operation boundary: operation must be explicitly allowed.
    checks["operation_allowed"] = action.operation in policy.allowed_operations
    if not checks["operation_allowed"]:
        reason = (f"operation {action.operation!r} not in "
                  f"{policy.allowed_operations!r}")

    # 5b. Role boundary: Ready/Merge/Deploy are NEVER implied by a Builder
    #     wake / review PASS / ACK / CI / runtime state.
    checks["no_implied_ready_merge_deploy"] = True
    if action.operation.lower() in LIFECYCLE_ACTIONS:
        if not policy.allowed_ready_merge_deploy:
            checks["no_implied_ready_merge_deploy"] = False
            reason = (f"operation {action.operation!r} requires separate "
                      f"action-specific authorization")

    # 6. One task / one scope: the episode task_id never switches.
    checks["task_scope_locked"] = bool(action.task_id) and action.task_id == policy.task_id
    if not checks["task_scope_locked"]:
        reason = (f"task {action.task_id!r} != policy task {policy.task_id!r}")

    # 7. Clean-worktree / contamination check.
    checks["clean_worktree"] = True
    if worktree is not None:
        if worktree.has_uncommitted_changes:
            # Unrelated pre-existing changes contaminate the controlled
            # mutation; only allow if all changed paths are in-scope.
            for p in worktree.changed_paths:
                if not _is_path_allowed(p, policy.allowed_paths):
                    checks["clean_worktree"] = False
                    reason = (f"dirty worktree contains unrelated change: "
                              f"{p!r}")
                    break
        if worktree.current_branch and worktree.current_branch != policy.branch:
            checks["clean_worktree"] = False
            reason = (f"worktree branch {worktree.current_branch!r} != "
                      f"policy {policy.branch!r}")

    ok = all(checks.values())
    return {"ok": ok, "checks": checks, "reason": reason,
            "blocked": not ok}


def evaluate_builder_wake(policy: ScopePolicy, task_id: str, repo: str,
                          branch: str, base_sha: str, head_sha: str,
                          operation: str = "fix",
                          target_paths: Optional[Tuple[str, ...]] = None,
                          worktree: Optional[WorktreeState] = None) -> dict:
    """Convenience: evaluate a Builder wake proposal against the policy.

    A Builder wake is an instruction to work within scope, not a concrete
    path proposal. `target_paths=None` means "in-scope whole-repo work": the
    path boundary is enforced via the worktree contamination check and any
    explicitly proposed paths are still validated. Empty explicit paths are
    treated as no-path-proposal (allowed), unlike a concrete action which
    must name at least one in-scope path.
    """
    paths = () if target_paths is None else target_paths
    action = ActionScope(
        task_id=task_id,
        repository=repo,
        branch=branch,
        base_sha=base_sha,
        head_sha=head_sha,
        target_paths=paths,
        operation=operation,
    )
    if target_paths is None:
        return _evaluate_scope_without_path_gate(policy, action, worktree)
    return evaluate_scope(policy, action, worktree)


def _evaluate_scope_without_path_gate(policy, action, worktree) -> dict:
    """evaluate_scope minus the 'non-empty target_paths' requirement (used
    for Builder wakes, which do not propose concrete paths)."""
    checks: dict = {}
    reason = None

    checks["binding_ok"] = policy.binding_ok
    if not checks["binding_ok"]:
        reason = ("policy not bound to an independent authoritative "
                  "project profile (canonical repository mismatch)")

    checks["repository_exact"] = (
        action.repository == policy.repository and bool(action.repository))
    if not checks["repository_exact"]:
        reason = f"repository {action.repository!r} != policy {policy.repository!r}"

    checks["not_protected_repository"] = (
        action.repository not in policy.protected_repositories)
    if not checks["not_protected_repository"]:
        reason = f"repository {action.repository!r} is protected"

    checks["branch_exact"] = bool(action.branch) and action.branch == policy.branch
    if not checks["branch_exact"]:
        reason = f"branch {action.branch!r} != policy {policy.branch!r}"

    checks["base_sha_exact"] = (
        bool(action.base_sha) and action.base_sha == policy.base_sha)
    if not checks["base_sha_exact"]:
        reason = f"base_sha {action.base_sha!r} != policy {policy.base_sha!r}"

    checks["head_exact"] = True
    if policy.head_sha and action.head_sha != policy.head_sha:
        checks["head_exact"] = False
        reason = f"head_sha {action.head_sha!r} != policy {policy.head_sha!r}"

    checks["paths_allowed"] = True
    for p in action.target_paths:
        if _is_protected(p, policy.protected_repositories):
            checks["paths_allowed"] = False
            reason = f"path {p!r} is a protected path"
            break
        if not _is_path_allowed(p, policy.allowed_paths):
            checks["paths_allowed"] = False
            reason = f"path {p!r} outside allowed paths {policy.allowed_paths!r}"
            break

    # P0-2: unreadable authoritative changed-file set is fail-closed, never
    # treated as "zero changes".
    checks["changed_files_readable"] = not policy.changed_files_unreadable
    if not checks["changed_files_readable"]:
        reason = ("authoritative PR changed-file set could not be read; "
                  "fail closed, no Builder wake")

    # P0-1 (local origin): the local git origin must equal the bound repo.
    checks["origin_repo_exact"] = True
    if policy.origin_repo:
        if not action.repository == policy.origin_repo:
            checks["origin_repo_exact"] = False
            reason = (f"local origin {policy.origin_repo!r} != bound "
                      f"repository {action.repository!r}")

    # P0-3: an unverifiable local worktree (None) must BLOCK contamination
    # checks, never skip them.
    checks["worktree_verifiable"] = worktree is not None
    if worktree is None:
        reason = "local git/worktree state unverifiable; fail closed"

    checks["operation_allowed"] = action.operation in policy.allowed_operations
    if not checks["operation_allowed"]:
        reason = (f"operation {action.operation!r} not in "
                  f"{policy.allowed_operations!r}")

    # P0-2 (wake path): validate the AUTHORITATIVE changed-file set (e.g.
    # `gh pr diff --name-only` vs the base) against the allowed-path /
    # protected-path boundary. This catches committed out-of-scope files that
    # are invisible once the worktree is clean, not just pre-wake dirty state.
    checks["changed_files_in_scope"] = True
    for f in policy.authoritative_changed_files:
        if _is_protected(f, policy.protected_repositories):
            checks["changed_files_in_scope"] = False
            reason = f"authoritative changed file {f!r} is a protected path"
            break
        if not _is_path_allowed(f, policy.allowed_paths):
            checks["changed_files_in_scope"] = False
            reason = (f"authoritative changed file {f!r} outside allowed "
                      f"paths {policy.allowed_paths!r}")
            break

    checks["no_implied_ready_merge_deploy"] = True
    if action.operation.lower() in LIFECYCLE_ACTIONS:
        if not policy.allowed_ready_merge_deploy:
            checks["no_implied_ready_merge_deploy"] = False
            reason = (f"operation {action.operation!r} requires separate "
                      f"action-specific authorization")

    checks["task_scope_locked"] = bool(action.task_id) and action.task_id == policy.task_id
    if not checks["task_scope_locked"]:
        reason = f"task {action.task_id!r} != policy task {policy.task_id!r}"

    checks["clean_worktree"] = True
    if worktree is not None:
        if worktree.has_uncommitted_changes:
            for p in worktree.changed_paths:
                if not _is_path_allowed(p, policy.allowed_paths):
                    checks["clean_worktree"] = False
                    reason = f"dirty worktree contains unrelated change: {p!r}"
                    break
        if worktree.current_branch and worktree.current_branch != policy.branch:
            checks["clean_worktree"] = False
            reason = (f"worktree branch {worktree.current_branch!r} != "
                      f"policy {policy.branch!r}")

    ok = all(checks.values())
    return {"ok": ok, "checks": checks, "reason": reason,
            "blocked": not ok}
