#!/usr/bin/env python3
"""MANUAL lifecycle firewall with authenticated Product Owner decisions.

Gate/violation files under ``.agent-bridge`` are operational evidence only.
They are never authorization. Product Owner decisions are executable only when
an external operator-signed document verifies through the OS-protected control
channel. Handwritten ``po_decision.json`` files are ignored.

For an active MANUAL task, remote CLOSED/MERGED also fails closed even if the
Builder deleted or redirected gate evidence: exact action-specific signed PO
approval is required to accept the terminal mutation.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from governloop_runtime import operator_channel

LIFECYCLE_ACTIONS = (
    "ready", "merge", "close", "reopen", "tag", "release", "deploy"
)
VALID_PO_DECISIONS = ("APPROVE", "REJECT", "CHANGES", "CHANGES_REQUESTED")
PO_SCHEMA = "governloop-po-decision-v1"
PO_NAMESPACE = "governloop-po-decision"
_GATE_REPORT = "gate_report.json"
_VIOLATION = "lifecycle_violation.json"


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write(path: str, data: dict) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass


def _exact(data: Optional[dict], repo: str, pr: str, head: str) -> bool:
    return bool(data) and (
        data.get("repo") == repo
        and str(data.get("pr")) == str(pr)
        and data.get("head") == head
    )


def read_gate_report(bridge_dir: str) -> Optional[dict]:
    return _read_json(os.path.join(bridge_dir, _GATE_REPORT))


def read_violation(bridge_dir: str) -> Optional[dict]:
    return _read_json(os.path.join(bridge_dir, _VIOLATION))


def _decision_path(repo: str, pr: str, head: str) -> Optional[Path]:
    root = operator_channel.control_root()
    if root is None:
        return None
    safe_repo = re.sub(r"[^A-Za-z0-9_.-]+", "_", repo)
    safe_pr = re.sub(r"[^0-9]+", "", str(pr))
    safe_head = re.sub(r"[^0-9A-Fa-f]+", "", head)
    if not safe_repo or not safe_pr or safe_head != head:
        return None
    return root / "po-decisions" / f"{safe_repo}__{safe_pr}__{safe_head}.json"


def read_po_decision(bridge_dir: str, repo: Optional[str] = None,
                     pr: Optional[str] = None,
                     head: Optional[str] = None) -> Optional[dict]:
    """Verify an external PO decision; bridge_dir is compatibility-only."""
    del bridge_dir
    if not (repo and pr is not None and head):
        return None
    path = _decision_path(repo, str(pr), head)
    if path is None:
        return None
    loaded = operator_channel.load_signed_document(path, PO_NAMESPACE)
    if not loaded.get("ok"):
        return None
    payload = loaded.get("payload") or {}
    if payload.get("schema") != PO_SCHEMA or not _exact(payload, repo, str(pr), head):
        return None
    decision = str(payload.get("decision") or "").upper()
    if decision not in VALID_PO_DECISIONS:
        return None
    action = str(payload.get("lifecycle_action") or "").strip().lower()
    if action and action not in LIFECYCLE_ACTIONS:
        return None
    return payload


def gate_applies(bridge_dir: str, repo: str, pr: str, head: str) -> bool:
    gate = read_gate_report(bridge_dir)
    return bool(_exact(gate, repo, pr, head) and gate.get("sent"))


def _valid_exact_po_decision(bridge_dir: str, repo: str, pr: str,
                             head: str) -> Optional[dict]:
    return read_po_decision(bridge_dir, repo, pr, head)


def waiting_for_po(bridge_dir: str, repo: str, pr: str, head: str) -> bool:
    return gate_applies(bridge_dir, repo, pr, head) and not bool(
        _valid_exact_po_decision(bridge_dir, repo, pr, head))


def lifecycle_action_authorized(bridge_dir: str, repo: str, pr: str,
                                head: str, action: str) -> bool:
    action = str(action or "").strip().lower()
    decision = _valid_exact_po_decision(bridge_dir, repo, pr, head)
    if not decision or str(decision.get("decision") or "").upper() != "APPROVE":
        return False
    return str(decision.get("lifecycle_action") or "").strip().lower() == action


def lifecycle_check(bridge_dir: str, repo: str, pr: str, head: str,
                    action: str) -> dict:
    action = str(action or "").strip().lower()
    if action not in LIFECYCLE_ACTIONS:
        return {"ok": True, "blocked": False, "action": action,
                "detail": "not a guarded lifecycle action"}
    if not gate_applies(bridge_dir, repo, pr, head):
        return {"ok": True, "blocked": False, "action": action,
                "detail": "no exact MANUAL gate recorded for this object"}
    if lifecycle_action_authorized(bridge_dir, repo, pr, head, action):
        return {"ok": True, "blocked": False, "action": action,
                "detail": "external action-specific PO signature verified"}
    state = "WAITING_PO_AUTH" if waiting_for_po(
        bridge_dir, repo, pr, head) else "PO_DECISION_RECEIVED"
    return {"ok": False, "blocked": True, "action": action, "state": state,
            "detail": (f"lifecycle action {action!r} lacks exact external "
                       "action-specific Product Owner APPROVE")}


def _record_violation(bridge_dir: str, repo: str, pr: str, head: str,
                      remote_state: str, action: str,
                      *, context: str = "after a MANUAL gate") -> dict:
    existing = read_violation(bridge_dir)
    if _exact(existing, repo, pr, head):
        return existing
    violation = {
        "protocol_version": "1", "repo": repo, "pr": str(pr), "head": head,
        "remote_state": remote_state, "action": action, "violation": True,
        "detail": (f"remote PR became {remote_state} {context} without signed "
                   f"PO approval for lifecycle action {action!r}"),
    }
    _atomic_write(os.path.join(bridge_dir, _VIOLATION), violation)
    return violation


def terminal_mutation_violation(bridge_dir: str, repo: str, pr: str,
                                head: str, remote_state: str) -> Optional[dict]:
    """Gate-evidence path used by the Watcher."""
    existing = read_violation(bridge_dir)
    if _exact(existing, repo, pr, head) and existing.get("violation"):
        return existing
    remote_state = str(remote_state or "").upper()
    if remote_state not in ("MERGED", "CLOSED"):
        return None
    action = "merge" if remote_state == "MERGED" else "close"
    check = lifecycle_check(bridge_dir, repo, pr, head, action)
    if not check.get("blocked"):
        return None
    try:
        return _record_violation(bridge_dir, repo, pr, head, remote_state, action)
    except OSError:
        return {"violation": True, "repo": repo, "pr": str(pr), "head": head,
                "remote_state": remote_state, "action": action,
                "detail": "unauthorized lifecycle mutation detected; persistence failed"}


def active_manual_terminal_violation(bridge_dir: str, repo: str, pr: str,
                                     head: str,
                                     remote_state: str) -> Optional[dict]:
    """Fail closed for terminal mutation on an *active MANUAL task*.

    This path deliberately does not require gate_report.json. A Builder must
    not be able to erase/redirect mutable gate evidence and thereby turn an
    unauthorized close/merge into accepted TERMINAL. Exact action-specific
    signed PO approval is the only positive exception.
    """
    existing = read_violation(bridge_dir)
    if _exact(existing, repo, pr, head) and existing.get("violation"):
        return existing
    remote_state = str(remote_state or "").upper()
    if remote_state not in ("MERGED", "CLOSED"):
        return None
    action = "merge" if remote_state == "MERGED" else "close"
    if lifecycle_action_authorized(bridge_dir, repo, pr, head, action):
        return None
    try:
        return _record_violation(
            bridge_dir, repo, pr, head, remote_state, action,
            context="while the MANUAL task was still active")
    except OSError:
        return {"violation": True, "repo": repo, "pr": str(pr), "head": head,
                "remote_state": remote_state, "action": action,
                "detail": "active MANUAL lifecycle violation detected; persistence failed"}
