#!/usr/bin/env python3
"""AGE-30 runtime automation CLI.

Usage:
  python -m agentops_runtime risk-evaluate --flags <flag>...
  python -m agentops_runtime review-intake <repo> <pr> <expected-head> [--json <pr.json>]
  python -m agentops_runtime task-intake <repo> <queue-dir> [--issues-json <issues.json>]
  python -m agentops_runtime transition <risk> <review> --repo R --pr N --task-id T \
      --deliverable-path P --deliverable-url U [--output-dir D] [--task-state S]

Transition command (runtime stop path):
  - LOW / MEDIUM: routes via route_decision (original behavior, no notify).
  - HIGH: MUST route via transition_with_po_notify(): query live PR HEAD,
    build concise completion report, send via Neutral Relay, read-back
    verify, then write WAITING_PO_AUTH. It is FORBIDDEN to reach
    WAITING_PO_AUTH by calling route_decision() alone and stopping.

Governance: never auto-merges, never auto-deploys, never grants PO
authorization. HIGH risk always routes to WAITING_PO_AUTH through the
mandatory notify step.
"""

import argparse
import json
import os
import sys

from .transition_controller import (
    route_decision, query_live_pr_head, transition_with_po_notify,
    build_completion_report, NeutralRelayNotifier, GptWebContextReadback,
)
from .github_poller import read_pr_head


def _transition(risk, review, args, sections=None):
    """Runtime transition path.

    For HIGH this MUST go through transition_with_po_notify() (mandatory
    notify before WAITING_PO_AUTH). Calling route_decision() alone and
    stopping is forbidden for HIGH.
    """
    if risk == "HIGH":
        if not args.repo or not args.pr:
            print(json.dumps({
                "error": "HIGH transition requires --repo and --pr",
                "route": "ERROR",
            }, indent=2))
            return 2
        # Query the CURRENT live PR HEAD (authoritative) — fail closed.
        live_head = query_live_pr_head(args.repo, args.pr)
        if not live_head:
            print(json.dumps({
                "error": "could not query live PR HEAD (fail closed)",
                "route": "ERROR",
                "pr": args.pr,
                "repo": args.repo,
            }, indent=2))
            return 2
        output_dir = args.output_dir or "/tmp/agentops_runtime_transition"
        os.makedirs(output_dir, exist_ok=True)
        result = transition_with_po_notify(
            risk_level="HIGH",
            review_decision=review,
            task_id=args.task_id or "AGE-UNKNOWN",
            repo=args.repo,
            pr=args.pr,
            head=live_head,
            deliverable_path=args.deliverable_path or "",
            deliverable_url=args.deliverable_url or "",
            completion_sections=sections or {},
            output_dir=output_dir,
            task_state_path=args.task_state,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

        # WAITING_PO_AUTH is the Watcher's START condition, not the task's
        # termination. Launch the persistent Control Watcher (detached) so
        # the Controller survives the Builder process exit.
        route = result.get("outcome", {}).get("route")
        if route == "WAITING_PO_AUTH" and getattr(args, "start_watcher", False):
            launched = _launch_watcher(args, live_head)
            print(json.dumps({"watcher": launched}, indent=2))
        return 0

    # LOW / MEDIUM: original behavior (route only, no notify).
    outcome = route_decision(risk, review)
    print(json.dumps(outcome.to_record(), indent=2))
    return 0


def _launch_watcher(args, head):
    """Spawn a detached Control Watcher process (survives Builder exit).

    The watcher writes its PID + runtime state and runs until a terminal
    state. Returns a dict describing the launch outcome.
    """
    import subprocess

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    tools_dir = os.path.dirname(pkg_dir)
    cmd = [
        sys.executable, "-m", "agentops_runtime", "watch",
        "--task-id", args.task_id or "AGE-UNKNOWN",
        "--repo", args.repo,
        "--pr", str(args.pr),
        "--head", head,
        "--deliverable-path", args.deliverable_path or "",
        "--deliverable-url", args.deliverable_url or "",
        "--interval", str(getattr(args, "watcher_interval", 600) or 600),
    ]
    if getattr(args, "watcher_state_dir", None):
        cmd += ["--state-dir", args.watcher_state_dir]
    env = dict(os.environ)
    # Both the tools dir (for the package) and the package dir (for the
    # direct cross-module imports used by control_watcher) must be on path.
    env["PYTHONPATH"] = (tools_dir + os.pathsep + pkg_dir
                         + os.pathsep + env.get("PYTHONPATH", ""))
    try:
        # start_new_session detaches from the Builder's process group so the
        # watcher survives the Builder CLI exit.
        proc = subprocess.Popen(
            cmd, env=env,
            stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"),
            start_new_session=True,
        )
        return {
            "launched": True,
            "pid": proc.pid,
            "cmd": " ".join(cmd),
        }
    except Exception as e:
        return {"launched": False, "error": str(e)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agentops_runtime", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_risk = sub.add_parser("risk-evaluate", help="Classify risk (AGE-29)")
    p_risk.add_argument("--flags", nargs="*", default=[],
                        help="flag names, e.g. --flags production_code deployment")

    p_rev = sub.add_parser("review-intake", help="Intake GitHub PR review (AGE-28)")
    p_rev.add_argument("repo")
    p_rev.add_argument("pr", type=int)
    p_rev.add_argument("expected_head")
    p_rev.add_argument("--json", dest="pr_json", default=None,
                       help="path to a PR JSON file (for tests)")

    p_task = sub.add_parser("task-intake", help="Discover Linear tasks (AGE-27)")
    p_task.add_argument("repo")
    p_task.add_argument("queue_dir")
    p_task.add_argument("--issues-json", dest="issues_json", default=None,
                        help="path to an issues JSON list (for tests)")

    p_tr = sub.add_parser("transition", help="Route decision + mandatory notify (AGE-24/29/30)")
    p_tr.add_argument("risk", choices=["LOW", "MEDIUM", "HIGH"])
    p_tr.add_argument("review",
                      choices=["PASS", "CHANGES_REQUESTED", "INCOMPLETE", "BLOCKED", "COMMENTED"])
    p_tr.add_argument("--repo", default=None)
    p_tr.add_argument("--pr", default=None)
    p_tr.add_argument("--task-id", default=None)
    p_tr.add_argument("--deliverable-path", default=None)
    p_tr.add_argument("--deliverable-url", default=None)
    p_tr.add_argument("--output-dir", default=None)
    p_tr.add_argument("--task-state", default=None)
    p_tr.add_argument("--start-watcher", action="store_true",
                      help="on HIGH WAITING_PO_AUTH, launch the persistent Control Watcher")
    p_tr.add_argument("--watcher-interval", dest="watcher_interval", type=int, default=600,
                      help="Control Watcher poll interval seconds (default 600 = 10 min)")
    p_tr.add_argument("--watcher-state-dir", dest="watcher_state_dir", default=None)
    p_tr.add_argument("--completion-sections-json", dest="completion_sections_json",
                      default=None, help="path to a JSON dict of completion report sections")

    p_watch = sub.add_parser("watch", help="Run the persistent Control Watcher loop (AGE-30)")
    p_watch.add_argument("--task-id", default=None)
    p_watch.add_argument("--repo", default=None)
    p_watch.add_argument("--pr", default=None)
    p_watch.add_argument("--head", default=None)
    p_watch.add_argument("--deliverable-path", default=None)
    p_watch.add_argument("--deliverable-url", default=None)
    p_watch.add_argument("--state-dir", default=None)
    p_watch.add_argument("--interval", type=int, default=600)

    p_rep = sub.add_parser("report", help="Send a concise Completion Report to GPT Web via Neutral Relay (guaranteed enforcer)")
    p_rep.add_argument("--task-id", default=None)
    p_rep.add_argument("--repo", default=None)
    p_rep.add_argument("--pr", default=None)
    p_rep.add_argument("--head", default=None)
    p_rep.add_argument("--deliverable-path", default=None)
    p_rep.add_argument("--deliverable-url", default=None)
    p_rep.add_argument("--sections-json", default=None)
    p_rep.add_argument("--output-dir", default=None)

    p_wake = sub.add_parser("wake", help="List pending BUILDER_WAKE events (Builder consumes review follow-ups)")
    p_wake.add_argument("--state-dir", default=None)

    args = parser.parse_args(argv)

    if args.command == "risk-evaluate":
        from .risk_evaluator import classify_risk
        flags = {f: True for f in args.flags}
        decision = classify_risk(**flags)
        print(json.dumps({"level": decision.level,
                          "reasons": decision.reasons,
                          "fail_closed": decision.fail_closed}, indent=2))
        return 0

    if args.command == "review-intake":
        from .review_intake import read_github_pr, review_from_github
        if args.pr_json:
            with open(args.pr_json) as f:
                pr_json = json.load(f)
            decision = review_from_github(args.repo, args.pr, args.expected_head, pr_json)
        else:
            decision = read_github_pr(args.repo, args.pr, args.expected_head)
        print(json.dumps({"state": decision.state, "decision": decision.decision,
                          "repo": decision.repo, "pr": decision.pr,
                          "head": decision.head, "fail_closed": decision.fail_closed}, indent=2))
        return 0

    if args.command == "task-intake":
        from .task_intake import discover, write_discovery_records
        if args.issues_json:
            with open(args.issues_json) as f:
                issues = json.load(f)
        else:
            issues = []
        tasks = discover(issues, args.repo)
        written = write_discovery_records(tasks, args.queue_dir)
        print(json.dumps({"discovered": len(tasks), "written": written}, indent=2))
        return 0

    if args.command == "transition":
        # Load completion sections (optional, for HIGH notify report).
        sections = {}
        if getattr(args, "completion_sections_json", None):
            with open(args.completion_sections_json) as f:
                sections = json.load(f)
        return _transition(args.risk, args.review, args, sections=sections)

    if args.command == "watch":
        from .control_watcher import ControlWatcher
        watcher = ControlWatcher(
            task_id=args.task_id or "AGE-UNKNOWN",
            repo=args.repo,
            pr=args.pr,
            head=args.head or "",
            deliverable_path=args.deliverable_path or "",
            deliverable_url=args.deliverable_url or "",
            state_dir=args.state_dir,
            interval=args.interval or 600,
        )
        ok = watcher.run_forever()
        return 0 if ok else 1

    if args.command == "report":
        # Guaranteed completion-report enforcer: send a concise Completion
        # Report to GPT Web via the existing Neutral Relay for ANY task
        # completion, independent of the watcher. This is the mechanism that
        # ensures every task reports to GPT Web (not reliant on memory).
        head = args.head or read_pr_head(args.repo, args.pr) or ""
        sections = {}
        if getattr(args, "sections_json", None):
            with open(args.sections_json) as f:
                sections = json.load(f)
        report = build_completion_report(
            task_id=args.task_id or "AGE-UNKNOWN",
            repo=args.repo, pr=args.pr, head=head,
            deliverable_path=args.deliverable_path or "",
            deliverable_url=args.deliverable_url or "",
            sections=sections,
        )
        out_dir = args.output_dir or "/tmp/agentops_runtime_report"
        os.makedirs(out_dir, exist_ok=True)
        notifier = NeutralRelayNotifier()
        delivery = notifier.send(report, out_dir)
        readback = GptWebContextReadback()
        rb = readback.verify(report)
        confirmed = delivery.ack_captured or rb.readback_confirmed
        result = {
            "report": report.correlation_id,
            "delivered": confirmed,
            "status": "DELIVERED" if confirmed else "DELIVERY_FAILED",
            "head": head,
            "pr": args.pr,
            "readback_confirmed": rb.readback_confirmed,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "wake":
        # Builder consumes pending BUILDER_WAKE events (driven by the
        # Control Watcher) to execute review follow-ups. Read-only: it lists
        # pending wakes; the Builder then executes the fix and pushes.
        import glob
        state_dir = args.state_dir or os.path.expanduser("~/.agentops/watcher")
        wakes = []
        for p in sorted(glob.glob(os.path.join(state_dir, "wake_*.json"))):
            try:
                with open(p) as f:
                    wakes.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                continue
        print(json.dumps({"pending_wakes": wakes}, indent=2, ensure_ascii=False))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
