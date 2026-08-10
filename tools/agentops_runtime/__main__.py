#!/usr/bin/env python3
"""AGE-30 thin AUTO/MANUAL runtime adapter — compatibility entrypoint.

`complete` is retained only for pre-v0.1 bridge compatibility and is
non-authoritative. Live PO authority and accepted completion are verified
through external signed control channels by the runtime.
"""

import argparse
import json
import sys

from .runtime_loop import decide
from .controller import ControlWatcher
from . import relay_client
from . import setup_wizard


def cmd_setup(args):
    return setup_wizard.run_setup(
        config_path=args.config_file,
        repository=args.repo,
        cdp_port=args.cdp_port,
        browser_profile=args.browser_profile,
        setup_port=args.setup_port,
        no_open=args.no_open,
    )


def cmd_complete(args):
    """Write legacy bridge completion only; runtime ignores it for COMPLETE."""
    import os
    from .runtime_loop import _bridge_dir
    bd = _bridge_dir()
    os.makedirs(bd, exist_ok=True)
    completion = {"repo": args.repo, "pr": str(args.pr), "head": args.head,
                  "completion": "COMPLETE"}
    with open(os.path.join(bd, "completion.json"), "w") as f:
        json.dump(completion, f, indent=2)
    print(json.dumps({"written": True, "authoritative": False,
                      "completion": completion}, indent=2))
    return 0


def cmd_step(args):
    outcome = decide(args.task_id, args.repo, args.pr)
    print(json.dumps(outcome, indent=2, ensure_ascii=False))
    return 0


def cmd_watch(args):
    watcher = ControlWatcher(args.task_id, args.repo, args.pr,
                             interval=args.interval or 600)
    ok = watcher.run_forever()
    return 0 if ok else 1


def cmd_final_result_review(args):
    from .runtime_loop import _bridge_dir
    with open(args.status_report) as f:
        payload = f.read()
    out = relay_client.final_result_auto_review(
        args.repo, args.pr, args.head, payload,
        _bridge_dir(), "/tmp/agentops_runtime_report",
        timeout=args.timeout)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if not out.get("status_delivered"):
        return 1
    if out.get("status_delivered") and out.get("binding_ok") is False:
        return 3
    if out.get("review_sent") and not out.get("succeeded"):
        return 2
    if out.get("review_sent") and not (out.get("review") or {}).get("ok"):
        return 2
    return 0


def cmd_report(args):
    with open(args.status_report) as f:
        payload = f.read()
    out = relay_client.send_status_report(payload, "/tmp/agentops_runtime_report")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("delivered") else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agentops_runtime", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup")
    p.add_argument("--repo", help="Repository to prefill as owner/repo")
    p.add_argument("--config-file", default=setup_wizard.DEFAULT_CONFIG_PATH)
    p.add_argument("--cdp-port", type=int)
    p.add_argument("--browser-profile")
    p.add_argument("--setup-port", type=int, default=0)
    p.add_argument("--no-open", action="store_true")

    p = sub.add_parser("run-auto")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)

    p = sub.add_parser("run-manual")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)

    p = sub.add_parser("watch")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--interval", type=int, default=600)

    p = sub.add_parser("report")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--status-report", required=True)

    p = sub.add_parser("final-result-review")
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--status-report", required=True)
    p.add_argument("--timeout", type=int, default=400)

    p = sub.add_parser("complete")
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--head", required=True)

    args = parser.parse_args(argv)
    if args.command == "setup":
        return cmd_setup(args)
    if args.command in ("run-auto", "run-manual"):
        return cmd_step(args)
    if args.command == "watch":
        return cmd_watch(args)
    if args.command == "report":
        return cmd_report(args)
    if args.command == "final-result-review":
        return cmd_final_result_review(args)
    if args.command == "complete":
        return cmd_complete(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
