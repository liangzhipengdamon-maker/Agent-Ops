"""Verify-only explicit external-path authority.

This is a narrow exception for controlled coding/governance tasks that need to
operate on one exact directory outside the governed repository. It is not a
generic filesystem authorization system and it never grants lifecycle actions.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import operator_channel

SCHEMA = "governloop-external-path-authority-v1"
SIGNATURE_NAMESPACE = "governloop-external-path-authority"
_ALLOWED_OPERATIONS = ("read", "create", "edit", "copy", "preserve-copy", "move")


def current_subject_id() -> str:
    """Standard-mode authenticated subject binding: current OS effective uid."""
    return f"local-os:uid:{os.geteuid()}"


def authority_path(task_id: str) -> Optional[Path]:
    if not task_id or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for ch in task_id):
        return None
    root = operator_channel.control_root()
    return (root / "external-authority" / f"{task_id}.json") if root else None


def _parse_time(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def _revoked(authority_id: str) -> bool:
    root = operator_channel.control_root()
    if root is None:
        return True
    path = root / "revocations.json"
    if not path.exists():
        return False
    if not operator_channel.protected_control_path(path):
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    ids = data.get("revoked_authority_ids") if isinstance(data, dict) else None
    return not isinstance(ids, list) or authority_id in {str(v) for v in ids}


def _canonical_root(value: object) -> tuple[Optional[Path], Optional[str]]:
    if not isinstance(value, str) or not value.strip():
        return None, "external allowed_root missing"
    raw = Path(value)
    if not raw.is_absolute():
        return None, "external allowed_root must be absolute"
    if ".." in raw.parts:
        return None, "external allowed_root contains traversal"
    try:
        root = raw.resolve(strict=True)
    except OSError as exc:
        return None, f"external allowed_root is not resolvable: {exc}"
    if not root.is_dir():
        return None, "external allowed_root must be an existing directory"
    if root == Path(root.anchor):
        return None, "filesystem root cannot be authorized as external root"
    home = Path.home().resolve(strict=False)
    if root == home:
        return None, "runtime home root cannot be authorized as external root"
    return root, None


def verify_external_authority(task_id: str, operation: str, target_path: str) -> dict:
    """Verify exact external-path authority and containment; fail closed."""
    path = authority_path(task_id)
    if path is None:
        return {"ok": False, "status": "BLOCKED", "detail": "invalid task id or control channel unavailable"}
    loaded = operator_channel.load_signed_document(path, SIGNATURE_NAMESPACE)
    if not loaded.get("ok"):
        return {"ok": False, "status": "BLOCKED", "detail": loaded.get("detail") or "external authority verification failed"}
    payload = loaded.get("payload") or {}
    required = ("schema", "authority_id", "scope_kind", "task_id", "subject_id", "allowed_root", "allowed_operations", "issued_at", "expires_at", "issuer_key_id")
    missing = [field for field in required if payload.get(field) in (None, "", [])]
    if missing:
        return {"ok": False, "status": "BLOCKED", "detail": f"external authority incomplete: {', '.join(missing)}"}
    if payload.get("schema") != SCHEMA or payload.get("scope_kind") != "external_path":
        return {"ok": False, "status": "BLOCKED", "detail": "external authority schema/scope unsupported"}
    if payload.get("task_id") != task_id:
        return {"ok": False, "status": "BLOCKED", "detail": "external authority task binding mismatch"}
    if payload.get("subject_id") != current_subject_id():
        return {"ok": False, "status": "BLOCKED", "detail": "external authority subject binding mismatch"}
    authority_id = str(payload.get("authority_id"))
    if _revoked(authority_id):
        return {"ok": False, "status": "BLOCKED", "detail": "external authority revoked or revocation state unreadable"}
    issued = _parse_time(payload.get("issued_at")); expires = _parse_time(payload.get("expires_at"))
    now = datetime.now(timezone.utc)
    if issued is None or expires is None or expires <= issued or now < issued or now >= expires:
        return {"ok": False, "status": "BLOCKED", "detail": "external authority outside validity window"}
    allowed_ops = tuple(str(v).lower() for v in payload.get("allowed_operations", []))
    if not allowed_ops or any(v not in _ALLOWED_OPERATIONS for v in allowed_ops):
        return {"ok": False, "status": "BLOCKED", "detail": "external authority contains unsupported operation"}
    operation = str(operation or "").strip().lower()
    if operation not in allowed_ops:
        return {"ok": False, "status": "BLOCKED", "detail": "external operation not authorized"}
    root, error = _canonical_root(payload.get("allowed_root"))
    if error:
        return {"ok": False, "status": "BLOCKED", "detail": error}
    raw_target = Path(target_path)
    if not raw_target.is_absolute() or ".." in raw_target.parts:
        return {"ok": False, "status": "BLOCKED", "detail": "target must be absolute and traversal-free"}
    try:
        target = raw_target.resolve(strict=False)
    except OSError as exc:
        return {"ok": False, "status": "BLOCKED", "detail": f"target path is not resolvable: {exc}"}
    try:
        target.relative_to(root)
    except ValueError:
        return {"ok": False, "status": "BLOCKED", "detail": "target escapes authorized external root"}
    return {"ok": True, "status": "READY", "authority_id": authority_id, "scope_kind": "external_path", "allowed_root": str(root), "operation": operation, "target": str(target), "payload": payload}
