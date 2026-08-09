#!/usr/bin/env python3
"""AGE-30 AUTO/MANUAL runtime loop — production entrypoint.

Commands:
  run-auto   --task-id T --repo R --pr N --branch B --worktree W
             Runs the AUTO loop: read Linear -> Builder -> GitHub -> review;
             CHANGES_REQUESTED/NOT_PASS -> fix -> new code HEAD -> review
             again; PASS + acceptance -> continue until criteria satisfied.
  run-manual --task-id T --repo R --pr N [--checkpoint C] [--watch]
             Runs until the named MANUAL checkpoint, then WAITING_PO_AUTH.
  watch      --task-id T --repo R --pr N --state-dir S [--interval I]
             Persistent Controller/Watcher; stops on PR/task closure.
  report     --repo R --pr N --task-id T --sections-json S [--head H]
             Fail-closed concise Completion Report to GPT Web.

No LOW/MEDIUM/HIGH risk classifier participates.
"""

import argparse
import json
import os
import subprocess
import sys

from .task_intake import spec_from_linear
from .runtime_loop import RuntimeLoop
from .delivery import (
    build_completion_report, NeutralRelayNotifier, GptWebContextReadback,
)


def _read_sections(path):
    with open(path) as f:
        return json.load(f)


def _head(repo, pr):
    from .review_intake import read_pr_head
    return read_pr_head(repo, int(pr)) or ""


def cmd_run_auto(args):
    spec = spec_from_linear(args.task_id)
    if spec is None:
        print(json.dumps({"error": "linear_unreadable",
                          "decision_request": "cannot read Linear task"}))
        return 2
    if not spec.mode:
        print(json.dumps({"error": "mode_missing_or_ambiguous",
                          "decision_request": "specify Execution Mode AUTO|MANUAL"}))
        return 2
    if spec.mode != "AUTO":
        print(json.dumps({"error": "task_is_manual",
                          "use": "run-manual"}))
        return 2
    loop = RuntimeLoop(args.task_id, args.repo, args.pr, args.state_dir)
    # One bounded step per wake; the Controller keeps calling until the
    # acceptance criteria are satisfied (AUTO) or the PR closes.
    st = loop.step("AUTO", None, acceptance_ok=args.acceptance_ok)
    print(json.dumps(st.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_run_manual(args):
    spec = spec_from_linear(args.task_id)
    if spec is None:
        print(json.dumps({"error": "linear_unreadable",
                          "decision_request": "cannot read Linear task"}))
        return 2
    if not spec.mode:
        print(json.dumps({"error": "mode_missing_or_ambiguous",
                          "decision_request": "specify Execution Mode AUTO|MANUAL"}))
        return 2
    if spec.mode != "MANUAL":
        print(json.dumps({"error": "task_is_auto", "use": "run-auto"}))
        return 2
    checkpoint = args.checkpoint or spec.checkpoint
    if not checkpoint:
        print(json.dumps({"error": "manual_checkpoint_missing",
                          "decision_request": "MANUAL task must name its PO checkpoint"}))
        return 2
    loop = RuntimeLoop(args.task_id, args.repo, args.pr, args.state_dir)
    st = loop.step("MANUAL", checkpoint, acceptance_ok=False)
    print(json.dumps(st.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_watch(args):
    from .controller import ControlWatcher
    from .runtime_loop import RuntimeLoop

    def step_fn():
        loop = RuntimeLoop(args.task_id, args.repo, args.pr, args.state_dir)
        st = loop.step("MANUAL" if getattr(args, "manual", False) else "AUTO",
                       getattr(args, "checkpoint", None),
                       acceptance_ok=getattr(args, "acceptance_ok", False))
        return st.phase

    watcher = ControlWatcher(args.task_id, args.repo, args.pr, args.state_dir,
                             interval=args.interval or 600)
    ok = watcher.run_forever(step_fn, interval_override=args.interval)
    return 0 if ok else 1


def cmd_report(args):
    head = args.head or _head(args.repo, args.pr)
    sections = _read_sections(args.sections_json)
    report = build_completion_report(args.repo, args.pr, head, sections)
    out_dir = args.state_dir or "/tmp/agentops_runtime_report"
    d = NeutralRelayNotifier().send(report, out_dir)
    rb = GptWebContextReadback().verify(report)
    confirmed = d.ack_captured or rb.readback_confirmed
    print(json.dumps({
        "report": report.correlation_id,
        "delivered": confirmed,
        "status": "DELIVERED" if confirmed else "DELIVERY_FAILED",
        "head": head,
        "pr": args.pr,
        "readback_confirmed": rb.readback_confirmed,
    }, indent=2, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agentops_runtime", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run-auto")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--acceptance-ok", action="store_true")

    p = sub.add_parser("run-manual")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--checkpoint", default=None)
    p.add_argument("--state-dir", required=True)

    p = sub.add_parser("watch")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--interval", type=int, default=600)
    p.add_argument("--manual", action="store_true")
    p.add_argument("--checkpoint", default=None)
    p.add_argument("--acceptance-ok", action="store_true")

    p = sub.add_parser("report")
    p.add_argument("--task-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--head", default=None)
    p.add_argument("--sections-json", required=True)
    p.add_argument("--state-dir", default=None)

    args = parser.parse_args(argv)

    if args.command == "run-auto":
        return cmd_run_auto(args)
    if args.command == "run-manual":
        return cmd_run_manual(args)
    if args.command == "watch":
        return cmd_watch(args)
    if args.command == "report":
        return cmd_report(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
