#!/usr/bin/env python3
"""AGE-30 thin AUTO/MANUAL runtime adapter — production entrypoint.

Commands:
  setup      [--repo R] [--no-open]
             Open a localhost-only first-run wizard that binds a dedicated
             ChatGPT reviewer conversation to the Neutral Relay config.
  run-auto   --task-id T --repo R --pr N
             One AUTO decision step (reads Linear mode + GitHub review).
  run-manual --task-id T --repo R --pr N
             One MANUAL decision step; pauses only at the named checkpoint.
  watch      --task-id T --repo R --pr N [--interval I]
             Persistent watcher; survives Builder exit; stops on PR/task
             closure or accepted completion.
  report     --task-id T --repo R --pr N --status-report S
             Send a status_report via the existing Neutral Relay (thin glue).
  final-result-review --repo R --pr N --head H --status-report S [--timeout T]
             Final Result Auto-Review: send status_report; ONLY if
             delivered=true AND STATE=WAITING_REVIEW, auto-send
             REQUEST: independent_review via the existing Neutral Relay and
             parse the verdict. WAITING_PO_AUTH never triggers review.
  po-decision --repo R --pr N --head H --decision APPROVE|REJECT|CHANGES
             Write a PO decision to the bridge so a WAITING_PO_AUTH loop
             resumes at the named MANUAL checkpoint (P0-2).
  complete   --repo R --pr N --head H
             Write accepted-completion evidence to the bridge (Builder writes
             only when acceptance is satisfied; drives COMPLETE).

Durable state is LoopX's job; GPT Web transport is the existing Neutral
Relay's job. This is only the AUTO/MANUAL control glue plus first-run setup.
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


def cmd_po_decision(args):
    """Write a PO decision to the bridge so a WAITING_PO_AUTH loop resumes
    (P0-2). The decision binds the exact PR+HEAD and is consumed by
    runtime_loop._po_decision on the next step."""
    import os
    from .runtime_loop import _bridge_dir
    bd = _bridge_dir()
    os.makedirs(bd, exist_ok=True)
    decision = {"repo": args.repo, "pr": str(args.pr), "head": args.head,
                "decision": args.decision.upper()}
    with open(os.path.join(bd, "po_decision.json"), "w") as f:
        json.dump(decision, f, indent=2)
    print(json.dumps({"written": True, "decision": decision}, indent=2))
    return 0


def cmd_complete(args):
    """Write accepted-completion evidence to the bridge (R5-P0-1). The
    Builder writes this ONLY when the task's acceptance criteria are
    satisfied; runtime_loop._accepted_completion requires the exact PR+HEAD
    binding before producing COMPLETE. Bare PASS never becomes COMPLETE."""
    import os
    from .runtime_loop import _bridge_dir
    bd = _bridge_dir()
    os.makedirs(bd, exist_ok=True)
    completion = {"repo": args.repo, "pr": str(args.pr), "head": args.head,
                  "completion": "COMPLETE"}
    with open(os.path.join(bd, "completion.json"), "w") as f:
        json.dump(completion, f, indent=2)
    print(json.dumps({"written": True, "completion": completion}, indent=2))
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
    """Final Result Auto-Review: send status_report; ONLY if delivered=true
    AND STATE=WAITING_REVIEW, auto-send REQUEST: independent_review via the
    existing Neutral Relay and parse the captured verdict. WAITING_PO_AUTH
    never triggers a review; deduped per PR+HEAD. P1-1: returns non-zero when
    the status report was not delivered or the independent review did not
    parse successfully, so callers never see process success on failure."""
    import os
    from .runtime_loop import _bridge_dir
    with open(args.status_report) as f:
        payload = f.read()
    out = relay_client.final_result_auto_review(
        args.repo, args.pr, args.head, payload,
        _bridge_dir(), "/tmp/agentops_runtime_report",
        timeout=args.timeout)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if not out.get("status_delivered"):
        return 1  # status_report not delivered
    if out.get("status_delivered") and out.get("binding_ok") is False:
        return 3  # ACKed but payload binding failed -> no auto-review ran
    if out.get("review_sent") and not out.get("succeeded"):
        return 2  # independent_review sent but failed to parse
    if out.get("review_sent") and not (out.get("review") or {}).get("ok"):
        return 2
    return 0


def cmd_report(args):
    # Thin glue to the existing Neutral Relay (transport only).
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
    p.add_argument("--config-file", default=setup_wizard.DEFAULT_CONFIG_PATH,
                   help="Neutral Relay config path")
    p.add_argument("--cdp-port", type=int,
                   help="AgentOps Chrome CDP port (defaults to existing config or 9233)")
    p.add_argument("--browser-profile",
                   help="AgentOps Chrome profile path (defaults to existing config)")
    p.add_argument("--setup-port", type=int, default=0,
                   help="Local setup UI port; 0 chooses an ephemeral port")
    p.add_argument("--no-open", action="store_true",
                   help="Do not auto-open the setup page; print its URL instead")

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
    if args.command == "po-decision":
        return cmd_po_decision(args)
    if args.command == "complete":
        return cmd_complete(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
