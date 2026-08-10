"""Verify-only GovernLoop positive authority.

The runtime can verify operator authority but cannot create/sign it. Authority
must be provisioned by an external operator/control identity through the fixed,
OS-protected control channel in ``operator_channel``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from . import operator_channel


SCHEMA = "governloop-authority-v2"
SIGNATURE_NAMESPACE = "governloop-authority"
POSITIVE_CANONICAL_ENV = (
    "GOVERNLOOP_SCOPE_REPOSITORY",
    "GOVERNLOOP_AUTHORIZED_BRANCH",
    "GOVERNLOOP_BASELINE_SHA",
    "GOVERNLOOP_ALLOWED_PATHS",
    "GOVERNLOOP_AUTHORIZED_OPERATIONS",
    "GOVERNLOOP_TRUSTED_REVIEWERS",
)
POSITIVE_LEGACY_ENV = (
    "AGENTOPS_SCOPE_REPOSITORY",
    "AGENTOPS_AUTHORIZED_BRANCH",
    "AGENTOPS_BASELINE_SHA",
    "AGENTOPS_ALLOWED_PATHS",
    "AGENTOPS_AUTHORIZED_OPERATIONS",
    "AGENTOPS_TRUSTED_REVIEWERS",
)
_REQUIRED_PAYLOAD_FIELDS = (
    "task_id", "repository", "branch", "baseline_sha",
    "allowed_paths", "allowed_operations", "trusted_reviewers",
)
_MISSING_SCOPE_FIELDS = list(_REQUIRED_PAYLOAD_FIELDS[1:])
_TASK_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ALLOWED_OPERATIONS = ("fix", "continue", "complete")


def _safe_task_id(task_id: str) -> str:
    value = (task_id or "").strip()
    if not value or not _TASK_RE.fullmatch(value):
        raise ValueError("task_id must contain only letters, digits, '.', '_' or '-'")
    return value


def authority_path(task_id: str) -> Optional[Path]:
    """Fixed external-control path; caller environment cannot redirect it."""
    root = operator_channel.control_root()
    if root is None:
        return None
    return root / "authority" / f"{_safe_task_id(task_id)}.json"


def _ignored_raw_fields() -> list[str]:
    return [name for name in POSITIVE_CANONICAL_ENV + POSITIVE_LEGACY_ENV
            if os.environ.get(name, "").strip()]


def verify_authority(task_id: str, expected_repo: Optional[str] = None) -> dict:
    """Verify one pre-existing externally signed operator authority bundle."""
    try:
        task_id = _safe_task_id(task_id)
    except ValueError as exc:
        return {"ok": False, "status": "BLOCKED", "missing": ["task_id"],
                "detail": str(exc)}

    ignored = _ignored_raw_fields()
    path = authority_path(task_id)
    if path is None:
        return {"ok": False, "status": "BLOCKED",
                "missing": list(_MISSING_SCOPE_FIELDS),
                "ignored_process_authority_fields": ignored,
                "detail": "OS operator control channel unavailable"}

    loaded = operator_channel.load_signed_document(path, SIGNATURE_NAMESPACE)
    if not loaded.get("ok"):
        return {"ok": False, "status": "BLOCKED",
                "missing": list(_MISSING_SCOPE_FIELDS),
                "ignored_process_authority_fields": ignored,
                "detail": loaded.get("detail") or "operator authority verification failed"}
    payload = loaded.get("payload") or {}

    if payload.get("schema") != SCHEMA:
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": "authority bundle schema unsupported"}
    missing = [field for field in _REQUIRED_PAYLOAD_FIELDS
               if payload.get(field) in (None, "", [])]
    if payload.get("task_id") != task_id:
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": "authority bundle task binding mismatch"}
    repository = str(payload.get("repository") or "")
    if not _REPO_RE.fullmatch(repository):
        missing.append("repository")
    if expected_repo and repository != expected_repo:
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": "authority bundle repository binding mismatch"}
    if not _SHA_RE.fullmatch(str(payload.get("baseline_sha") or "")):
        missing.append("baseline_sha")
    operations = [str(v).lower() for v in (payload.get("allowed_operations") or [])]
    if any(op not in _ALLOWED_OPERATIONS for op in operations):
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": "authority bundle contains invalid/non-scope operation"}
    if missing:
        return {"ok": False, "status": "BLOCKED",
                "missing": sorted(set(missing)),
                "detail": "authority bundle incomplete"}

    return {
        "ok": True,
        "status": "READY",
        "missing": [],
        "authority_id": payload.get("authority_id"),
        "path": str(path),
        "payload": payload,
        "ignored_process_authority_fields": ignored,
        "detail": loaded.get("detail"),
    }


def clear_positive_process_authority() -> None:
    for name in POSITIVE_CANONICAL_ENV + POSITIVE_LEGACY_ENV:
        os.environ.pop(name, None)


def apply_verified_authority(task_id: str, expected_repo: Optional[str] = None) -> dict:
    """Project only verified values into both canonical and compatibility readers.

    Raw caller values in both namespaces are cleared before projection. The
    legacy aliases are populated directly from the same verified payload so a
    direct ``agentops_runtime`` caller cannot fall back to profile/raw-env
    reviewer or scope authority.
    """
    status = verify_authority(task_id, expected_repo=expected_repo)
    clear_positive_process_authority()
    os.environ["AGENTOPS_AUTHORITY_VERIFIED"] = "1" if status.get("ok") else "0"
    os.environ["AGENTOPS_AUTHORITY_ERROR"] = status.get("detail", "")
    os.environ["GOVERNLOOP_ALLOW_READY_MERGE_DEPLOY"] = ""
    os.environ["AGENTOPS_ALLOW_READY_MERGE_DEPLOY"] = ""
    if not status.get("ok"):
        return status

    payload = status["payload"]
    values = {
        "SCOPE_REPOSITORY": payload["repository"],
        "AUTHORIZED_BRANCH": payload["branch"],
        "BASELINE_SHA": payload["baseline_sha"],
        "ALLOWED_PATHS": ",".join(payload["allowed_paths"]),
        "AUTHORIZED_OPERATIONS": ",".join(payload["allowed_operations"]),
        "TRUSTED_REVIEWERS": ",".join(payload["trusted_reviewers"]),
    }
    for suffix, value in values.items():
        os.environ[f"GOVERNLOOP_{suffix}"] = value
        os.environ[f"AGENTOPS_{suffix}"] = value
    return status
