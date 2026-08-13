"""Protected operator-side provisioning without private-key access.

The CLI intentionally never reads signing keys. It installs already-signed
GovernLoop control documents under a runtime user's fixed protected control
root, manages local revocation state, and provides read-only inspection.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path

try:
    import pwd
except ImportError:  # pragma: no cover
    pwd = None

KINDS = {
    "repository": ("authority", "governloop-authority-v2"),
    "external_path": ("external-authority", "governloop-external-path-authority-v1"),
    "lifecycle": ("po-decisions", "governloop-po-decision-v1"),
}


def _account(user):
    if pwd is None:
        raise RuntimeError("Standard Mode operator CLI requires POSIX identities")
    try:
        return pwd.getpwnam(user)
    except KeyError as exc:
        raise RuntimeError(f"runtime user {user!r} does not exist") from exc


def _root(user):
    account = _account(user)
    if account.pw_uid == os.geteuid():
        raise RuntimeError("operator identity must differ from Builder/runtime uid")
    return Path(account.pw_dir) / ".governloop" / "control"


def _owned(root):
    try:
        st = root.stat()
    except OSError as exc:
        raise RuntimeError(f"protected control root unavailable: {root}") from exc
    if not root.is_dir() or st.st_uid != os.geteuid():
        raise RuntimeError("control root must be owned by operator uid")


def _writable(directory):
    class Guard:
        def __enter__(self):
            self.mode = stat.S_IMODE(directory.stat().st_mode)
            directory.chmod(self.mode | 0o700)
        def __exit__(self, *args):
            directory.chmod(0o555)
    return Guard()


def _sub(root, name):
    with _writable(root):
        (root / name).mkdir(mode=0o700, exist_ok=True)
    directory = root / name
    if directory.stat().st_uid != os.geteuid():
        raise RuntimeError("control subdirectory has wrong owner")
    directory.chmod(0o555)
    return directory


def _write(path, text):
    with _writable(path.parent):
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o444)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    path.chmod(0o444)


def _load_signed(path, expected_schema):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"signed document unreadable: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("payload"), dict) or not isinstance(doc.get("ssh_signature"), str):
        raise RuntimeError("signed document envelope malformed")
    if doc["payload"].get("schema") != expected_schema:
        raise RuntimeError("signed document schema does not match requested kind")
    return doc


def cmd_authorize(args):
    root = _root(args.runtime_user)
    _owned(root)
    sub, schema = KINDS[args.kind]
    doc = _load_signed(args.signed_document, schema)
    payload = doc["payload"]
    task = str(payload.get("task_id") or "")
    if not task or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for ch in task):
        raise RuntimeError("signed authority has invalid task_id")
    target = _sub(root, sub) / f"{task}.json"
    _write(target, json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return {"ok": True, "action": "authorize", "kind": args.kind, "path": str(target), "authority_id": payload.get("authority_id"), "payload": payload}


def cmd_approve(args):
    root = _root(args.runtime_user)
    _owned(root)
    sub, schema = KINDS["lifecycle"]
    doc = _load_signed(args.signed_document, schema)
    payload = doc["payload"]
    repo = str(payload.get("repo") or "").replace("/", "_")
    pr = str(payload.get("pr") or "")
    head = str(payload.get("head") or "")
    if not repo or not pr.isdigit() or len(head) != 40:
        raise RuntimeError("signed lifecycle decision lacks exact repo/PR/HEAD")
    target = _sub(root, sub) / f"{repo}__{pr}__{head}.json"
    _write(target, json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return {"ok": True, "action": "approve", "path": str(target), "payload": payload}


def _revocations(root):
    path = root / "revocations.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"revocation state unreadable: {exc}") from exc
    ids = data.get("revoked_authority_ids") if isinstance(data, dict) else None
    if not isinstance(ids, list):
        raise RuntimeError("revocation state malformed")
    return {str(item) for item in ids}


def cmd_revoke(args):
    root = _root(args.runtime_user)
    _owned(root)
    ids = _revocations(root)
    ids.add(args.authority_id)
    target = root / "revocations.json"
    _write(target, json.dumps({"schema": "governloop-revocations-v1", "revoked_authority_ids": sorted(ids)}, indent=2, sort_keys=True) + "\n")
    return {"ok": True, "action": "revoke", "authority_id": args.authority_id, "path": str(target)}


def cmd_inspect(args):
    root = _root(args.runtime_user)
    items = []
    for sub, _ in KINDS.values():
        directory = root / sub
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    payload = doc.get("payload", {})
                except (OSError, json.JSONDecodeError):
                    payload = {"unreadable": True}
                items.append({"kind": sub, "path": str(path), "payload": payload})
    return {"ok": True, "action": "inspect", "control_root": str(root), "revoked_authority_ids": sorted(_revocations(root)) if root.exists() else [], "items": items}


def build_parser():
    parser = argparse.ArgumentParser(prog="governloop-operator", description="Provision externally signed GovernLoop authority into a protected control root")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("authorize", "approve"):
        command = sub.add_parser(name)
        command.add_argument("--runtime-user", required=True)
        command.add_argument("--signed-document", required=True)
        if name == "authorize":
            command.add_argument("--kind", choices=("repository", "external_path"), required=True)
    command = sub.add_parser("revoke")
    command.add_argument("--runtime-user", required=True)
    command.add_argument("--authority-id", required=True)
    command = sub.add_parser("inspect")
    command.add_argument("--runtime-user", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        out = {"authorize": cmd_authorize, "approve": cmd_approve, "revoke": cmd_revoke, "inspect": cmd_inspect}[args.command](args)
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "status": "BLOCKED", "detail": str(exc)}, indent=2))
        return 2
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
