"""Verify-only manual approval evidence for one narrow Doctor exception.

Manual approval is not a second authority channel. It may only release an exact
worktree-scope contamination check after the primary signed authority already
verified. All other BLOCKED checks remain hard blocks.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import authority, operator_channel

SCHEMA = "governloop-manual-approval-v1"
SIGNATURE_NAMESPACE = "governloop-manual-approval"
_REQUEST_RE = re.compile(r"^[0-9a-f]{64}$")
_APPROVABLE_DETAIL = "uncommitted paths outside operator-bound scope"


def is_approvable(check):
    data = check.get("data") or {}
    return (
        check.get("status") == "BLOCKED"
        and check.get("name") == "worktree_scope"
        and check.get("detail") == _APPROVABLE_DETAIL
        and bool(data.get("outside_paths"))
    )


def request_id(task_id, check):
    material = {
        "task_id": authority._safe_task_id(task_id),
        "check_name": str(check.get("name") or ""),
        "detail": str(check.get("detail") or ""),
        "data": check.get("data"),
    }
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def approval_path(task_id, rid):
    task = authority._safe_task_id(task_id)
    if not _REQUEST_RE.fullmatch(rid or ""):
        raise ValueError("request_id must be 64 lowercase hex characters")
    root = operator_channel.control_root()
    return root / "manual_approvals" / task / f"{rid}.json" if root else None


def verify_approval(task_id, rid):
    try:
        task = authority._safe_task_id(task_id)
        path = approval_path(task, rid)
    except ValueError as exc:
        return {"ok": False, "detail": str(exc)}
    if path is None:
        return {"ok": False, "detail": "operator control channel unavailable"}
    loaded = operator_channel.load_signed_document(path, SIGNATURE_NAMESPACE)
    if not loaded.get("ok"):
        return {"ok": False, "detail": loaded.get("detail") or "approval verification failed"}
    payload = loaded.get("payload") or {}
    if payload.get("schema") != SCHEMA:
        return {"ok": False, "detail": "manual approval schema unsupported"}
    if payload.get("task_id") != task:
        return {"ok": False, "detail": "manual approval task binding mismatch"}
    if payload.get("request_id") != rid:
        return {"ok": False, "detail": "manual approval request binding mismatch"}
    if payload.get("status") != "APPROVED":
        return {"ok": False, "detail": "manual approval is not APPROVED"}
    return {"ok": True, "approval_id": payload.get("approval_id"), "detail": loaded.get("detail")}


def apply_to_checks(task_id, checks):
    requests = []
    for check in checks:
        if not is_approvable(check):
            continue
        rid = request_id(task_id, check)
        check["request_id"] = rid
        verified = verify_approval(task_id, rid)
        if verified.get("ok"):
            check["status"] = "MANUALLY_APPROVED"
            check["manual_approval"] = {"approval_id": verified.get("approval_id"), "request_id": rid}
        else:
            requests.append({"task_id": task_id, "request_id": rid, "check": check.get("name")})
    return checks, requests
