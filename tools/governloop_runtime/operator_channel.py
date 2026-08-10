"""Verify-only external operator control channel.

Security model:
- GovernLoop runtime has NO signing key and NO API/CLI that can mint authority.
- The operator public key and signed control documents live under a fixed OS
  account home path, not a caller-controlled GOVERNLOOP_HOME.
- The control directory and documents must be owned by a different OS uid and
  not writable by the Builder/runtime uid. If that separation is absent,
  verification fails closed.
- Signatures use OpenSSH ssh-keygen -Y with a domain-separated namespace.

This intentionally requires process/credential separation for strong local
security. A same-uid Builder cannot be treated as cryptographically distinct
from the Product Owner merely by convention.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

try:
    import pwd
except ImportError:  # pragma: no cover - strong channel is POSIX-only in v0.1
    pwd = None


OPERATOR_IDENTITY = "governloop-operator"
PUBLIC_KEY_NAME = "operator_authority.pub"


def os_account_home() -> Optional[Path]:
    """Resolve home from the OS account database, never HOME/GOVERNLOOP_HOME."""
    if pwd is None:
        return None
    try:
        return Path(pwd.getpwuid(os.geteuid()).pw_dir)
    except (KeyError, OSError):
        return None


def control_root() -> Optional[Path]:
    home = os_account_home()
    return (home / ".governloop" / "control") if home else None


def public_key_path() -> Optional[Path]:
    root = control_root()
    return (root / PUBLIC_KEY_NAME) if root else None


def _owned_by_runtime(path: Path) -> bool:
    try:
        return path.stat().st_uid == os.geteuid()
    except OSError:
        return True


def _mode_writable(path: Path) -> bool:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return True
    return bool(mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def protected_control_path(path: Path) -> bool:
    """Require a real OS ownership boundary from the runtime/Builder uid."""
    try:
        if not path.exists() or not path.is_file():
            return False
        parent = path.parent
        if not parent.exists() or not parent.is_dir():
            return False
        if _owned_by_runtime(path) or _owned_by_runtime(parent):
            return False
        if _mode_writable(path) or _mode_writable(parent):
            return False
        return True
    except OSError:
        return False


def canonical_payload_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def verify_ssh_signature(payload: dict, signature: str, namespace: str) -> dict:
    """Verify an OpenSSH detached signature using the pinned operator key."""
    pub = public_key_path()
    if pub is None or not protected_control_path(pub):
        return {"ok": False, "detail": "operator public-key channel is absent or writable by runtime uid"}
    try:
        public_line = pub.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return {"ok": False, "detail": f"operator public key unreadable: {exc}"}
    if not public_line.startswith(("ssh-ed25519 ", "ssh-rsa ", "ecdsa-sha2-")):
        return {"ok": False, "detail": "operator public key format unsupported"}
    if not signature or "BEGIN SSH SIGNATURE" not in signature:
        return {"ok": False, "detail": "missing OpenSSH detached signature"}

    try:
        with tempfile.TemporaryDirectory(prefix="governloop-verify-") as td:
            allowed = Path(td) / "allowed_signers"
            sigfile = Path(td) / "signature"
            allowed.write_text(f"{OPERATOR_IDENTITY} {public_line}\n", encoding="utf-8")
            sigfile.write_text(signature, encoding="utf-8")
            res = subprocess.run(
                ["ssh-keygen", "-Y", "verify",
                 "-f", str(allowed),
                 "-I", OPERATOR_IDENTITY,
                 "-n", namespace,
                 "-s", str(sigfile)],
                input=canonical_payload_bytes(payload),
                capture_output=True, timeout=20,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "detail": f"signature verifier unavailable: {exc}"}
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or b"signature rejected").decode(
            "utf-8", errors="replace").strip()
        return {"ok": False, "detail": detail[-300:] or "signature rejected"}
    return {"ok": True, "detail": "external operator signature verified"}


def load_signed_document(path: Path, namespace: str) -> dict:
    """Read and verify one operator-owned signed JSON document."""
    if not protected_control_path(path):
        return {"ok": False, "detail": "signed control document absent or writable by runtime uid"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "detail": f"signed control document unreadable: {exc}"}
    if not isinstance(doc, dict) or not isinstance(doc.get("payload"), dict):
        return {"ok": False, "detail": "signed control document schema invalid"}
    signature = doc.get("ssh_signature")
    if not isinstance(signature, str):
        return {"ok": False, "detail": "signed control document missing ssh_signature"}
    verified = verify_ssh_signature(doc["payload"], signature, namespace)
    if not verified.get("ok"):
        return verified
    return {"ok": True, "payload": doc["payload"], "detail": verified["detail"]}
