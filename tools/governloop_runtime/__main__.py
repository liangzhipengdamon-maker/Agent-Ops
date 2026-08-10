#!/usr/bin/env python3
"""GovernLoop CLI — governed autonomy for coding agents.

Commands:
  setup                bind a dedicated ChatGPT reviewer conversation
  run-auto             execute one bounded AUTO decision step
  run-manual           execute one bounded MANUAL decision step
  watch                keep the Controller/Watcher alive
  report               send a status report through the Neutral Relay
  final-result-review  deliver status and request exact-HEAD review
  po-decision          bind a Product Owner decision to exact PR + HEAD
  complete             record accepted-completion evidence
"""

import argparse
import json
import os
import sys

from ._compat import configure_process
from . import setup_wizard


def _legacy_runtime():
    configure_process()
    from agentops_runtime import relay_client
    from agentops_runtime.controller import ControlWatcher
    from agentops_runtime.runtime_loop import decide, _bridge_dir
    return relay_client, ControlWatcher, decide, _bridge_dir


def cmd_setup(args):
    configure_process()
    return setup_wizard.run_setup(
        config_path=args.config_file,
        repository=args.repo,
        cdp_port=args.cdp_port,
        browser_profile=args.browser_profile,
        setup_port=args.setup_port,
        no_open=args.no_open,
    )


def cmd_step(args):
    _, _, decide, _ = _legacy_runtime()
    outcome = decide(args.task_id, args.repo, args.pr)
    print(json.dumps(outcome, indent=2, ensure_ascii=False))
    return 0


def cmd_watch(args):
    _, ControlWatcher, _, _ = _legacy_runtime()
    watcher = ControlWatcher(args.task_id, args.repo, args.pr,
                             interval=args.interval or 600)
    return 0 if watcher.run_forever() else 1


def cmd_report(args):
    relay_client, _, _, _ = _legacy_runtime()
    with open(args.status_report, encoding="utf-8") as handle:
        payload = handle.read()
    out = relay_client.send_status_report(
        payload, "/tmp/governloop_runtime_report")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("delivered") else 1


def cmd_final_result_review(args):
    relay_client, _, _, bridge_dir = _legacy_runtime()
    with open(args.status_report, encoding="utf-8") as handle:
        payload = handle.read()
    out = relay_client.final_result_auto_review(
        args.repo, args.pr, args.head, payload,
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


def cmd_po_decision(args):
    _, _, _, bridge_dir = _legacy_runtime()
    bd = bridge_dir()
    os.makedirs(bd, exist_ok=True)
    decision = {
        "repo": args.repo,
        "pr": str(args.pr),
        "head": args.head,
        "decision": args.decision.upper(),
    }
    with open(os.path.join(bd, "po_decision.json"), "w", encoding="utf-8") as handle:
        json.dump(decision, handle, indent=2)
    print(json.dumps({"written": True, "decision": decision}, indent=2))
    return 0


def cmd_complete(args):
    _, _, _, bridge_dir = _legacy_runtime()
    bd = bridge_dir()
    os.makedirs(bd, exist_ok=True)
    completion = {
        "repo": args.repo,
        "pr": str(args.pr),
        "head": args.head,
        "completion": "COMPLETE",
    }
    with open(os.path.join(bd, "completion.json"), "w", encoding="utf-8") as handle:
        json.dump(completion, handle, indent=2)
    print(json.dumps({"written": True, "completion": completion}, indent=2))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="governloop", description="GovernLoop — governed autonomy for coding agents")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="bind a ChatGPT reviewer conversation")
    p.add_argument("--repo", help="Repository to prefill as owner/repo")
    p.add_argument("--config-file", default=setup_wizard.DEFAULT_CONFIG_PATH)
    p.add_argument("--cdp-port", type=int)
    p.add_argument("--browser-profile")
    p.add_argument("--setup-port", type=int, default=0)
    p.add_argument("--no-open", action="store_true")

    for name in ("run-auto", "run-manual"):
        p = sub.add_parser(name)
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

    p = sub.add_parser("po-decision")
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--decision", required=True,
                   choices=["APPROVE", "REJECT", "CHANGES"])

    p = sub.add_parser("complete")
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--head", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
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
    if args.command == "po-decision":
        return cmd_po_decision(args)
    if args.command == "complete":
        return cmd_complete(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
