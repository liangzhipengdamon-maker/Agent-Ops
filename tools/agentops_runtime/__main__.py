#!/usr/bin/env python3
"""AGE-30 runtime automation CLI.

Usage:
  python -m agentops_runtime risk-evaluate <json>
  python -m agentops_runtime review-intake <repo> <pr> <expected-head> [--json <pr.json>]
  python -m agentops_runtime task-intake <repo> <queue-dir> [--issues-json <issues.json>]
  python -m agentops_runtime transition <risk> <review>

Governance: never auto-merges, never auto-deploys, never grants PO
authorization. HIGH risk always routes to WAITING_PO_AUTH.
"""

import argparse
import json
import sys


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

    p_tr = sub.add_parser("transition", help="Route decision (AGE-24/29)")
    p_tr.add_argument("risk", choices=["LOW", "MEDIUM", "HIGH"])
    p_tr.add_argument("review",
                      choices=["PASS", "CHANGES_REQUESTED", "INCOMPLETE", "BLOCKED", "COMMENTED"])

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
        from .transition_controller import route_decision
        outcome = route_decision(args.risk, args.review)
        print(json.dumps(outcome.to_record(), indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
