"""Verify-only GovernLoop positive authority.

The runtime can verify operator authority but cannot create/sign it. Authority
must be provisioned by an external operator/control identity through the fixed,
OS-protected control channel in ``operator_channel``.

An ``interactive_local`` fallback source (`task_scope`) is also verified here.
That source lives outside ``operator_channel``'s uid separation: it is a
same-user/same-uid file under the OS-resolved account home, and ``integrity_sha256``
plus ``confirmation_method`` record provenance only — they do not block a same-uid
Agent from rewriting the file. The interactive-local mode is a same-user trust
boundary by design (see docs/governance/CURRENT_RUNTIME_RULES.md: positive
authority rules); it is opt-in via ``configure_process(..., mode="interactive_local")``
and is *not* the default. Lifecycle / completion / external-signer review
decisions do not consume this channel.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

from . import operator_channel


SCHEMA = "governloop-authority-v2"
SCHEMA_TASK_SCOPE = "governloop-task-scope-v1"
SIGNATURE_NAMESPACE = "governloop-authority"
TASK_SCOPE_CONFIRMATION_METHOD = "interactive_local_tty_yes"
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


def task_scope_dir() -> Optional[Path]:
    """Same-uid directory for interactive-local task-scope records.

    Distinct from ``operator_channel.control_root()`` / ``authority`` so the
    uid-separated rules from ``operator_channel`` are not applied here. The
    channel is opt-in via ``interactive_local`` mode.
    """
    home = operator_channel.os_account_home()
    if home is None:
        return None
    return home / ".governloop" / "task_scope"


def task_scope_path(task_id: str) -> Optional[Path]:
    """Resolve the interactive-local task-scope file for ``task_id``."""
    root = task_scope_dir()
    if root is None:
        return None
    return root / f"{_safe_task_id(task_id)}.json"


def _task_scope_integrity(payload: dict) -> str:
    """Compute integrity_sha256 over a task-scope record, excluding the
    integrity_sha256 field itself (the same convention as signed
    operator documents that exclude the signature)."""
    excluded = {k: v for k, v in payload.items() if k != "integrity_sha256"}
    return hashlib.sha256(
        operator_channel.canonical_payload_bytes(excluded)
    ).hexdigest()


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


def verify_task_scope(task_id: str, expected_repo: Optional[str] = None) -> dict:
    """Verify an interactive-local task-scope record.

    The task-scope channel is read/write from a same-uid (non
    operator-uid-separated) path. It is intentional that interactive-local
    mode carries a same-user trust boundary, not an OS-uid-separated
    authority boundary. ``integrity_sha256`` and ``confirmation_method``
    are provenance / integrity markers only — a same-uid Agent that can
    write the file can rewrite every field including the markers.
    """
    try:
        task_id = _safe_task_id(task_id)
    except ValueError as exc:
        return {"ok": False, "status": "BLOCKED", "missing": ["task_id"],
                "detail": str(exc)}

    path = task_scope_path(task_id)
    if path is None:
        return {"ok": False, "status": "BLOCKED",
                "missing": list(_MISSING_SCOPE_FIELDS),
                "detail": "interactive-local task-scope home directory unavailable"}
    if not path.exists() or not path.is_file():
        return {"ok": False, "status": "BLOCKED",
                "missing": list(_MISSING_SCOPE_FIELDS),
                "detail": ("no interactive-local task-scope recorded for this task; "
                           "run `governloop setup-task-scope`")}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": "BLOCKED",
                "missing": list(_MISSING_SCOPE_FIELDS),
                "detail": f"interactive-local task-scope file unreadable: {exc}"}
    if not isinstance(doc, dict):
        return {"ok": False, "status": "BLOCKED",
                "missing": list(_MISSING_SCOPE_FIELDS),
                "detail": "interactive-local task-scope file malformed (not a JSON object)"}

    expected_integrity = doc.get("integrity_sha256")
    if not expected_integrity:
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": "interactive-local task-scope missing integrity_sha256 marker"}
    actual_integrity = _task_scope_integrity(doc)
    if expected_integrity != actual_integrity:
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": "interactive-local task-scope integrity_sha256 mismatch"}

    if doc.get("schema") != SCHEMA_TASK_SCOPE:
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": (f"interactive-local task-scope schema unsupported: "
                           f"{doc.get('schema')!r}")}
    if doc.get("confirmation_method") != TASK_SCOPE_CONFIRMATION_METHOD:
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": (f"interactive-local task-scope confirmation_method must be "
                           f"{TASK_SCOPE_CONFIRMATION_METHOD!r}")}
    if doc.get("task_id") != task_id:
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": "interactive-local task-scope task_id binding mismatch"}

    repository = str(doc.get("repository") or "")
    if not _REPO_RE.fullmatch(repository):
        return {"ok": False, "status": "BLOCKED", "missing": ["repository"],
                "detail": "interactive-local task-scope repository format invalid"}
    if expected_repo and repository != expected_repo:
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": "interactive-local task-scope repository binding mismatch"}

    branch = str(doc.get("branch") or "")
    if not branch:
        return {"ok": False, "status": "BLOCKED", "missing": ["branch"],
                "detail": "interactive-local task-scope branch missing"}

    baseline_sha = str(doc.get("baseline_sha") or "")
    if not _SHA_RE.fullmatch(baseline_sha):
        return {"ok": False, "status": "BLOCKED", "missing": ["baseline_sha"],
                "detail": "interactive-local task-scope baseline_sha must be 40-char hex"}

    head_sha = str(doc.get("head_sha") or "")
    if head_sha and not _SHA_RE.fullmatch(head_sha):
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": ("interactive-local task-scope head_sha must be 40-char hex "
                           "when set; leave absent to not pin PR head")}

    operations = [str(v).lower() for v in (doc.get("allowed_operations") or [])]
    if any(op not in _ALLOWED_OPERATIONS for op in operations):
        return {"ok": False, "status": "BLOCKED", "missing": [],
                "detail": (f"interactive-local task-scope allowed_operations must be "
                           f"a subset of {_ALLOWED_OPERATIONS}; lifecycle operations "
                           f"require external signed PO")}

    allowed_paths = doc.get("allowed_paths")
    if not isinstance(allowed_paths, list) or not allowed_paths or not all(
            isinstance(p, str) and p for p in allowed_paths):
        return {"ok": False, "status": "BLOCKED", "missing": ["allowed_paths"],
                "detail": ("interactive-local task-scope allowed_paths must be a "
                           "non-empty list of strings")}

    trusted_reviewers = doc.get("trusted_reviewers") or []
    if not isinstance(trusted_reviewers, list) or not all(
            isinstance(r, str) for r in trusted_reviewers):
        return {"ok": False, "status": "BLOCKED", "missing": ["trusted_reviewers"],
                "detail": ("interactive-local task-scope trusted_reviewers must be a "
                           "list of strings")}

    return {
        "ok": True,
        "status": "INTERACTIVE_LOCAL",
        "missing": [],
        "authority_id": doc.get("authority_id") or f"interactive-local-{task_id}",
        "path": str(path),
        "payload": doc,
        "head_sha": head_sha,
        "detail": ("interactive-local task-scope file verified; same-user trust "
                   "boundary, integrity_sha256 is provenance only"),
    }


def clear_positive_process_authority() -> None:
    for name in POSITIVE_CANONICAL_ENV + POSITIVE_LEGACY_ENV:
        os.environ.pop(name, None)


def _verify_via_mode(task_id: str, expected_repo: Optional[str], mode: str) -> dict:
    """Resolve positive authority by ``mode`` and return the verified record
    (signed or interactive-local) plus a ``source`` marker. Fails closed when
    no source accepts the request."""
    if mode == "signed":
        verified = verify_authority(task_id, expected_repo=expected_repo)
        verified["_source"] = "signed"
        return verified
    if mode == "interactive_local":
        signed = verify_authority(task_id, expected_repo=expected_repo)
        if signed.get("ok"):
            signed["_source"] = "signed"
            return signed
        ts = verify_task_scope(task_id, expected_repo=expected_repo)
        if ts.get("ok"):
            ts["_source"] = "interactive_local"
            return ts
        return {
            "ok": False, "status": "BLOCKED",
            "_source": "interactive_local",
            "missing": signed.get("missing") or list(_MISSING_SCOPE_FIELDS),
            "detail": (f"signed authority unavailable ({signed.get('detail')}); "
                       f"interactive-local task-scope unavailable ({ts.get('detail')})"),
        }
    return {
        "ok": False, "status": "BLOCKED", "_source": mode,
        "missing": list(_MISSING_SCOPE_FIELDS),
        "detail": f"unknown authority mode {mode!r}",
    }


def apply_verified_authority(task_id: str,
                             expected_repo: Optional[str] = None,
                             mode: str = "signed") -> dict:
    """Project only verified values into both canonical and compatibility readers.

    Modes:
      * ``"signed"`` (default) — only the externally signed operator authority
        document under the OS-protected control channel is accepted.
      * ``"interactive_local"`` — same as signed, with a fallback to the
        same-uid task-scope file when signed authority is unavailable.

    Raw caller values in both namespaces are cleared before projection, so a
    direct ``agentops_runtime`` caller cannot fall back to profile/raw-env
    reviewer or scope authority.

    ``TRUSTED_REVIEWERS`` is projected into both namespaces regardless of
    mode so the live review reader keeps working once authority is resolved.
    """
    status = _verify_via_mode(task_id, expected_repo, mode)
    source = status.pop("_source", mode)
    clear_positive_process_authority()
    os.environ["AGENTOPS_AUTHORITY_VERIFIED"] = "1" if status.get("ok") else "0"
    os.environ["AGENTOPS_AUTHORITY_ERROR"] = status.get("detail", "")
    os.environ["AGENTOPS_AUTHORITY_SOURCE"] = source
    os.environ["GOVERNLOOP_ALLOW_READY_MERGE_DEPLOY"] = ""
    os.environ["AGENTOPS_ALLOW_READY_MERGE_DEPLOY"] = ""
    if not status.get("ok"):
        return status

    payload = status["payload"]
    trusted = payload.get("trusted_reviewers") or []
    if not isinstance(trusted, list):
        trusted = []
    values = {
        "SCOPE_REPOSITORY": payload["repository"],
        "AUTHORIZED_BRANCH": payload["branch"],
        "BASELINE_SHA": payload["baseline_sha"],
        "ALLOWED_PATHS": ",".join(payload["allowed_paths"]),
        "AUTHORIZED_OPERATIONS": ",".join(payload["allowed_operations"]),
        "TRUSTED_REVIEWERS": ",".join(trusted),
    }
    for suffix, value in values.items():
        os.environ[f"GOVERNLOOP_{suffix}"] = value
        os.environ[f"AGENTOPS_{suffix}"] = value
    return status
