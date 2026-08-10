"""Verify-only accepted-completion evidence.

Completion is lifecycle-bearing evidence. Builder/runtime bridge files are
non-authoritative; only an externally provisioned, OS-protected OpenSSH-signed
document can produce COMPLETE.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import operator_channel

SCHEMA = "governloop-completion-v1"
SIGNATURE_NAMESPACE = "governloop-completion"
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def completion_path(repo: str, pr: str) -> Optional[Path]:
    if not _REPO_RE.fullmatch(repo or "") or not str(pr).isdigit():
        return None
    root = operator_channel.control_root()
    if root is None:
        return None
    safe_repo = repo.replace("/", "__")
    return root / "completion" / f"{safe_repo}--pr-{pr}.json"


def verify_completion(repo: str, pr: str, head: str) -> dict:
    """Verify exact externally signed completion evidence; fail closed."""
    if not _REPO_RE.fullmatch(repo or ""):
        return {"ok": False, "detail": "invalid repository binding"}
    if not str(pr).isdigit():
        return {"ok": False, "detail": "invalid PR binding"}
    if not _SHA_RE.fullmatch(head or ""):
        return {"ok": False, "detail": "invalid HEAD binding"}
    path = completion_path(repo, str(pr))
    if path is None:
        return {"ok": False, "detail": "completion control path unavailable"}
    loaded = operator_channel.load_signed_document(path, SIGNATURE_NAMESPACE)
    if not loaded.get("ok"):
        return loaded
    payload = loaded.get("payload") or {}
    if payload.get("schema") != SCHEMA:
        return {"ok": False, "detail": "completion schema unsupported"}
    if payload.get("repo") != repo:
        return {"ok": False, "detail": "completion repository binding mismatch"}
    if str(payload.get("pr")) != str(pr):
        return {"ok": False, "detail": "completion PR binding mismatch"}
    if str(payload.get("head") or "").lower() != head.lower():
        return {"ok": False, "detail": "completion HEAD binding mismatch"}
    if str(payload.get("completion") or "").upper() != "COMPLETE":
        return {"ok": False, "detail": "completion verdict is not COMPLETE"}
    return {"ok": True, "detail": loaded.get("detail"), "payload": payload,
            "path": str(path)}
