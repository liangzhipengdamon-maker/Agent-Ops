#!/usr/bin/env python3
"""GovernLoop CLI — governed autonomy for coding agents.

Authority is verify-only in the runtime. Product Owner lifecycle decisions are
accepted only from external signed control evidence. Legacy `complete` writes
non-authoritative bridge compatibility evidence only.

The ``setup-task-scope`` / ``interactive-local`` commands opt the runtime into
``mode="interactive_local"`` — a same-user/same-uid trust boundary backed by a
local task-scope file under ``~/.governloop/task_scope/<task>.json``. The
``confirmation_method`` and ``integrity_sha256`` markers in that file are
provenance / integrity hints; they do not block a same-uid Agent from
rewriting the file. Run / Merge / Deploy / external-signer review decisions
do not consume this channel.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid

from ._compat import configure_process
from . import authority
from . import doctor
from . import operator_channel
from . import setup_wizard


def _legacy_runtime(task_id=None, expected_repo=None, mode="signed"):
    authority_status = configure_process(task_id=task_id, expected_repo=expected_repo,
                                          mode=mode)
    from agentops_runtime import relay_client
    from agentops_runtime.controller import ControlWatcher
    from agentops_runtime.runtime_loop import decide, _bridge_dir
    return relay_client, ControlWatcher, decide, _bridge_dir, authority_status


def _print_authority_block(task_id, repo, status, mode="signed"):
    if mode == "interactive_local":
        decision_request = (
            "no positive authority source resolved for this task; "
            "rerun `governloop setup-task-scope` to confirm a task scope, "
            "or switch back to `governloop run-auto` once external signed "
            "operator authority is provisioned under the protected control channel")
    else:
        decision_request = (
            "external operator must provision a signed authority document "
            "through the protected control channel; runtime cannot mint it")
    out = {"mode": mode, "phase": "BLOCKED", "review_decision": "AUTHORITY_UNBOUND",
           "findings": [], "checkpoint_reached": False, "task_id": task_id,
           "repo": repo, "authority": status, "decision_request": decision_request}
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_setup(args):
    configure_process()
    return setup_wizard.run_setup(config_path=args.config_file, repository=args.repo,
                                  cdp_port=args.cdp_port, browser_profile=args.browser_profile,
                                  setup_port=args.setup_port, no_open=args.no_open)


def cmd_setup_authority(args):
    """Render one exact, non-authoritative request for the external operator.

    This command deliberately does not sign, install, or mutate positive
    authority. It only removes the need to hand-assemble the v2 payload and
    tells the Product Owner/operator where the existing protected channel
    expects the signed document.
    """
    try:
        task_id = authority._safe_task_id(args.task_id)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_REQUEST", "detail": str(exc)}, indent=2))
        return 2
    if not authority._REPO_RE.fullmatch(args.repo or ""):
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "repo must be owner/repository"}, indent=2))
        return 2
    if not args.branch:
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "branch is required"}, indent=2))
        return 2
    if not authority._SHA_RE.fullmatch(args.baseline_sha or ""):
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "baseline-sha must be a full 40-character Git SHA"}, indent=2))
        return 2
    if not args.allow_path:
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "at least one --allow-path is required"}, indent=2))
        return 2
    if not args.trusted_reviewer:
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "at least one --trusted-reviewer is required"}, indent=2))
        return 2
    operations = args.operation or list(authority._ALLOWED_OPERATIONS)
    invalid = [op for op in operations if op not in authority._ALLOWED_OPERATIONS]
    if invalid:
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": f"unsupported scope operation(s): {', '.join(invalid)}"}, indent=2))
        return 2

    payload = {
        "schema": authority.SCHEMA,
        "authority_id": args.authority_id,
        "task_id": task_id,
        "repository": args.repo,
        "branch": args.branch,
        "baseline_sha": args.baseline_sha,
        "allowed_paths": list(args.allow_path),
        "allowed_operations": list(operations),
        "trusted_reviewers": list(args.trusted_reviewer),
    }
    authority_path = authority.authority_path(task_id)
    public_key_path = operator_channel.public_key_path()
    out = {
        "status": "OPERATOR_ACTION_REQUIRED",
        "authoritative": False,
        "mutations_performed": False,
        "payload": payload,
        "canonical_payload": operator_channel.canonical_payload_bytes(payload).decode("utf-8"),
        "operator_channel": {
            "signature_namespace": authority.SIGNATURE_NAMESPACE,
            "signer_identity": operator_channel.OPERATOR_IDENTITY,
            "public_key_path": str(public_key_path) if public_key_path else None,
            "authority_document_path": str(authority_path) if authority_path else None,
            "requirements": [
                "sign with an external operator identity; GovernLoop runtime cannot sign",
                "operator public key, control directory, and signed document must not be owned or writable by the Builder/runtime uid",
                "install a JSON document containing this exact payload plus its OpenSSH detached signature",
            ],
        },
        "next_required_external_action": (
            "external operator signs canonical_payload with OpenSSH namespace "
            f"{authority.SIGNATURE_NAMESPACE!r}, installs operator_authority.pub and the signed "
            "authority document at the reported protected paths, then rerun governloop authority-check"
        ),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_authority_check(args):
    out = authority.verify_authority(args.task_id, expected_repo=args.repo)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok") else 2


def cmd_task_scope_check(args):
    out = authority.verify_task_scope(args.task_id, expected_repo=args.repo)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok") else 2


def cmd_setup_task_scope(args):
    """Confirm and record one exact task scope for interactive-local mode.

    The confirm step is a single explicit ``YES`` typed on the terminal stdin;
    piping / non-tty stdin / other answers fail closed without writing the
    task-scope record. ``isatty`` only gates that stdin can be read at all
    and is not itself the approval.
    """
    try:
        task_id = authority._safe_task_id(args.task_id)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_REQUEST", "detail": str(exc)}, indent=2))
        return 2
    if not authority._REPO_RE.fullmatch(args.repo or ""):
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "repo must be owner/repository"}, indent=2))
        return 2
    if not args.branch:
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "branch is required"}, indent=2))
        return 2
    if not authority._SHA_RE.fullmatch(args.baseline_sha or ""):
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "baseline-sha must be a full 40-character Git SHA"},
                         indent=2))
        return 2
    if args.head_sha and not authority._SHA_RE.fullmatch(args.head_sha):
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "head-sha (optional) must be a full 40-character Git SHA"},
                         indent=2))
        return 2
    if not args.allow_path:
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "at least one --allow-path is required"}, indent=2))
        return 2
    if not args.trusted_reviewer:
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": "at least one --trusted-reviewer is required"},
                         indent=2))
        return 2
    operations = args.operation or list(authority._ALLOWED_OPERATIONS)
    invalid = [op for op in operations if op not in authority._ALLOWED_OPERATIONS]
    if invalid:
        print(json.dumps({"status": "INVALID_REQUEST",
                          "detail": (f"unsupported scope operation(s): "
                                     f"{', '.join(invalid)}; lifecycle ops require "
                                     f"external signed PO")},
                         indent=2))
        return 2

    target_path = authority.task_scope_path(task_id)
    if target_path is None:
        print(json.dumps({"status": "BLOCKED", "detail": "OS account home unavailable"},
                         indent=2))
        return 2
    target_dir = target_path.parent
    if target_path.exists() and not args.replace:
        print(json.dumps({
            "status": "TASK_SCOPE_EXISTS",
            "task_id": task_id,
            "path": str(target_path),
            "detail": ("interactive-local task-scope already recorded; rerun with "
                       "--replace to overwrite (still requires YES on the terminal)"),
        }, indent=2, ensure_ascii=False))
        return 0

    if not sys.stdout.isatty() or not sys.stdin.isatty():
        print(json.dumps({
            "status": "INTERACTIVE_TERMINAL_REQUIRED",
            "task_id": task_id,
            "detail": ("setup-task-scope requires an interactive terminal with both "
                       "stdin and stdout attached so the user can confirm the exact "
                       "task scope by typing YES; isatty is a precondition, not the "
                       "approval"),
        }, indent=2, ensure_ascii=False))
        return 6

    payload = {
        "schema": authority.SCHEMA_TASK_SCOPE,
        "authority_id": args.authority_id or f"interactive-local-{task_id}",
        "task_id": task_id,
        "repository": args.repo,
        "branch": args.branch,
        "baseline_sha": args.baseline_sha,
        "head_sha": args.head_sha or "",
        "allowed_paths": list(args.allow_path),
        "allowed_operations": list(operations),
        "trusted_reviewers": list(args.trusted_reviewer),
        "bound_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "confirmation_method": authority.TASK_SCOPE_CONFIRMATION_METHOD,
    }
    payload["integrity_sha256"] = hashlib.sha256(
        operator_channel.canonical_payload_bytes(payload)
    ).hexdigest()

    sys.stdout.write(
        "=== interactive-local task-scope for task "
        f"{task_id} (same-user trust boundary) ===\n")
    sys.stdout.write(
        "schema: " + authority.SCHEMA_TASK_SCOPE + "\n")
    sys.stdout.write(
        "confirmation_method: " + authority.TASK_SCOPE_CONFIRMATION_METHOD + "\n\n")
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n\n")
    sys.stdout.write(
        "Approve this exact task scope? Type YES to confirm: ")
    sys.stdout.flush()
    try:
        answer = sys.stdin.readline().strip()
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        print(json.dumps({
            "status": "APPROVAL_ABORTED",
            "task_id": task_id,
            "detail": "KeyboardInterrupt during confirmation; no file written",
        }, indent=2, ensure_ascii=False))
        return 130
    if answer != "YES":
        print(json.dumps({
            "status": "APPROVAL_MISMATCH",
            "task_id": task_id,
            "detail": (f"answer must be exactly 'YES' after trimming whitespace; "
                       f"got {answer!r}"),
            "mutations_performed": False,
        }, indent=2, ensure_ascii=False))
        return 6

    target_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=target_path.name + ".", dir=str(target_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target_path)
        os.chmod(target_path, 0o600)
    except OSError as exc:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        print(json.dumps({
            "status": "WRITE_FAILED",
            "task_id": task_id,
            "detail": f"could not write task-scope file: {exc}",
        }, indent=2, ensure_ascii=False))
        return 7

    readback = authority.verify_task_scope(task_id, expected_repo=args.repo)
    if not readback.get("ok"):
        try:
            os.unlink(target_path)
        except OSError:
            pass
        print(json.dumps({
            "status": "WRITE_VERIFY_FAILED",
            "task_id": task_id,
            "path": str(target_path),
            "detail": readback.get("detail"),
            "mutations_performed": False,
        }, indent=2, ensure_ascii=False))
        return 7

    print(json.dumps({
        "status": "TASK_SCOPE_CONFIRMED",
        "task_id": task_id,
        "repository": args.repo,
        "branch": args.branch,
        "baseline_sha": args.baseline_sha,
        "path": str(target_path),
        "integrity_sha256": payload["integrity_sha256"][:12],
        "authority_id": payload["authority_id"],
        "mode": "interactive_local",
        "trust_boundary": "same-user / same-uid; not an OS-uid-separated authority",
        "next_action": ("rerun `governloop interactive-local` (or any task runner) "
                        "to project this task-scope into the live runtime env"),
        "mutations_performed": True,
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_doctor(args):
    out = doctor.run_doctor(args.task_id, args.repo, args.pr,
                            probe_reviewer=not args.no_reviewer_probe)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("status") in ("READY", "BOOTSTRAP_REQUIRED") else 2


def cmd_step(args):
    _, _, decide, _, authority_status = _legacy_runtime(
        task_id=args.task_id, expected_repo=args.repo, mode="signed")
    if not authority_status.get("ok"):
        _print_authority_block(args.task_id, args.repo, authority_status, mode="signed")
        return 4
    outcome = decide(args.task_id, args.repo, args.pr)
    outcome.setdefault("authority", {"status": authority_status.get("status"),
                                      "authority_id": authority_status.get("authority_id")})
    print(json.dumps(outcome, indent=2, ensure_ascii=False))
    return 0


_REVIEW_GATE_PHASES = frozenset({"REVIEW"})


def cmd_interactive_local(args):
    """Interactive-local runtime entry. Same caller shape as run-auto.

    Issue #49: reuse the existing GovernLoop-owned Neutral Relay and the
    exact-bound review protocol already owned by the runtime. A *new*
    independent review is requested ONLY when the runtime is genuinely waiting
    for one — phase == "REVIEW" with no concluded verdict yet. PASSED and FIX
    are post-review outcomes (review already decided) and MUST NOT trigger
    another review. The handoff uses ``relay_client.final_result_auto_review``
    — the same contract ``cmd_final_result_review`` uses, including its
    internal (pr, head) dedupe. We do NOT reimplement dedupe/report logic.

    Lifecycle/status reporting for WAITING_PO_AUTH is already performed
    automatically inside ``decide()`` via ``_gate_status_report``; we do not
    duplicate it. BLOCKED/TERMINAL stay print-only, matching existing run-auto
    behavior. Relay failure is fail-closed (non-zero exit, never silent
    success); this never grants Ready/Merge/Deploy or alters task scope.
    """
    relay_client, _, decide, _bridge_dir_fn, authority_status = _legacy_runtime(
        task_id=args.task_id, expected_repo=args.repo, mode="interactive_local")
    if not authority_status.get("ok"):
        _print_authority_block(args.task_id, args.repo, authority_status,
                                mode="interactive_local")
        return 4
    outcome = decide(args.task_id, args.repo, args.pr)
    outcome.setdefault("authority", {"status": authority_status.get("status"),
                                      "authority_id": authority_status.get("authority_id")})

    handoff = None
    phase = outcome.get("phase") or "UNKNOWN"
    if phase in _REVIEW_GATE_PHASES:
        head = outcome.get("head") or ""
        req_id = f"IL_HANDOFF_{uuid.uuid4().hex[:12]}"
        payload = (
            f"REVIEW_REQUEST_ID: {req_id}\n"
            f"REPO: {args.repo}\n"
            f"PR: {args.pr}\n"
            f"HEAD: {head}\n"
            f"REQUEST: status_report\n"
            f"STATE: WAITING_REVIEW\n"
            f"GATE: {phase}\n"
        )
        result = relay_client.final_result_auto_review(
            args.repo, args.pr, head, payload, _bridge_dir_fn(),
            "/tmp/governloop_runtime_report")
        delivered = bool(result.get("status_delivered")) or bool(result.get("deduped"))
        handoff = {
            "handoff": "auto_review", "state": phase, "review_gate": True,
            "deduped": bool(result.get("deduped")),
            "status_delivered": result.get("status_delivered"),
            "review_sent": result.get("review_sent"),
            "succeeded": result.get("succeeded"),
            "binding_ok": result.get("binding_ok"),
            "delivered": delivered, "ok": delivered,
            "detail": result.get("detail"),
        }

    if handoff is not None:
        outcome["handoff"] = handoff

    print(json.dumps(outcome, indent=2, ensure_ascii=False))
    # Fail-closed: a review handoff that was attempted but not delivered is a
    # hard failure. We never silently claim the reviewer received the result.
    if handoff is not None and not handoff.get("delivered"):
        return 1
    return 0


def cmd_watch(args):
    _, ControlWatcher, _, _, authority_status = _legacy_runtime(task_id=args.task_id, expected_repo=args.repo)
    if not authority_status.get("ok"):
        _print_authority_block(args.task_id, args.repo, authority_status)
        return 4
    return 0 if ControlWatcher(args.task_id, args.repo, args.pr,
                               interval=args.interval or 600).run_forever() else 1


def cmd_report(args):
    relay_client, _, _, _, _ = _legacy_runtime()
    with open(args.status_report, encoding="utf-8") as handle:
        payload = handle.read()
    out = relay_client.send_status_report(payload, "/tmp/governloop_runtime_report")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("delivered") else 1


def cmd_final_result_review(args):
    relay_client, _, _, bridge_dir, _ = _legacy_runtime()
    with open(args.status_report, encoding="utf-8") as handle:
        payload = handle.read()
    out = relay_client.final_result_auto_review(args.repo, args.pr, args.head, payload,
                                                bridge_dir(), "/tmp/governloop_runtime_report",
                                                timeout=args.timeout)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if not out.get("status_delivered"):
        return 1
    if out.get("binding_ok") is False:
        return 3
    if out.get("review_sent") and not out.get("succeeded"):
        return 2
    if out.get("review_sent") and not (out.get("review") or {}).get("ok"):
        return 2
    return 0


def cmd_complete(args):
    _, _, _, bridge_dir, _ = _legacy_runtime()
    bd = bridge_dir(); os.makedirs(bd, exist_ok=True)
    completion = {"repo": args.repo, "pr": str(args.pr), "head": args.head,
                  "completion": "COMPLETE"}
    with open(os.path.join(bd, "completion.json"), "w", encoding="utf-8") as handle:
        json.dump(completion, handle, indent=2)
    print(json.dumps({"written": True, "authoritative": False,
                      "completion": completion}, indent=2))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="governloop", description="GovernLoop — governed autonomy for coding agents")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup"); p.add_argument("--repo"); p.add_argument("--config-file", default=setup_wizard.DEFAULT_CONFIG_PATH); p.add_argument("--cdp-port", type=int); p.add_argument("--browser-profile"); p.add_argument("--setup-port", type=int, default=0); p.add_argument("--no-open", action="store_true")
    p = sub.add_parser("setup-authority", help="render a non-authoritative request for the external operator"); p.add_argument("--task-id", required=True); p.add_argument("--repo", required=True); p.add_argument("--branch", required=True); p.add_argument("--baseline-sha", required=True); p.add_argument("--authority-id", default="operator-authority"); p.add_argument("--allow-path", action="append", required=True); p.add_argument("--operation", action="append", choices=authority._ALLOWED_OPERATIONS); p.add_argument("--trusted-reviewer", action="append", required=True)
    p = sub.add_parser("authority-check"); p.add_argument("--task-id", required=True); p.add_argument("--repo", required=True)
    p = sub.add_parser("setup-task-scope", help="confirm and record one exact task scope for interactive-local mode (TTY-only YES confirm)")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--baseline-sha", required=True)
    p.add_argument("--head-sha", default="", help="optional PR HEAD pin (40-char hex); leave blank to not pin")
    p.add_argument("--authority-id", default=None)
    p.add_argument("--allow-path", action="append", required=True)
    p.add_argument("--operation", action="append", choices=authority._ALLOWED_OPERATIONS)
    p.add_argument("--trusted-reviewer", action="append", required=True)
    p.add_argument("--replace", action="store_true", help="overwrite the existing task-scope record (still requires YES)")
    p = sub.add_parser("task-scope-check", help="verify the recorded interactive-local task-scope record (read-only)"); p.add_argument("--task-id", required=True); p.add_argument("--repo")
    p = sub.add_parser("doctor", help="read-only first-task readiness diagnostics"); p.add_argument("--task-id", required=True); p.add_argument("--repo", required=True); p.add_argument("--pr"); p.add_argument("--no-reviewer-probe", action="store_true")
    for name in ("run-auto", "run-manual"):
        p = sub.add_parser(name); p.add_argument("--task-id", required=True); p.add_argument("--repo", required=True); p.add_argument("--pr", required=True)
    p = sub.add_parser("interactive-local", help="run task steps in interactive-local mode (same-user task-scope fallback)")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p = sub.add_parser("watch"); p.add_argument("--task-id", required=True); p.add_argument("--repo", required=True); p.add_argument("--pr", required=True); p.add_argument("--interval", type=int, default=600)
    p = sub.add_parser("report"); p.add_argument("--task-id", required=True); p.add_argument("--repo", required=True); p.add_argument("--pr", required=True); p.add_argument("--status-report", required=True)
    p = sub.add_parser("final-result-review"); p.add_argument("--repo", required=True); p.add_argument("--pr", required=True); p.add_argument("--head", required=True); p.add_argument("--status-report", required=True); p.add_argument("--timeout", type=int, default=400)
    p = sub.add_parser("complete"); p.add_argument("--repo", required=True); p.add_argument("--pr", required=True); p.add_argument("--head", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "setup": return cmd_setup(args)
    if args.command == "setup-authority": return cmd_setup_authority(args)
    if args.command == "authority-check": return cmd_authority_check(args)
    if args.command == "setup-task-scope": return cmd_setup_task_scope(args)
    if args.command == "task-scope-check": return cmd_task_scope_check(args)
    if args.command == "doctor": return cmd_doctor(args)
    if args.command in ("run-auto", "run-manual"): return cmd_step(args)
    if args.command == "interactive-local": return cmd_interactive_local(args)
    if args.command == "watch": return cmd_watch(args)
    if args.command == "report": return cmd_report(args)
    if args.command == "final-result-review": return cmd_final_result_review(args)
    if args.command == "complete": return cmd_complete(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
