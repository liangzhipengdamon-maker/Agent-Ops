"""Thin public CLI wrapper for fresh-agent discoverability.

All existing GovernLoop commands are delegated unchanged to the canonical
runtime CLI. This wrapper owns only the read-only `instructions` discovery
entry and one help hint for coding agents.
"""

from __future__ import annotations

import sys

from . import __main__ as runtime_cli


AGENT_INSTRUCTIONS = """GovernLoop Agent Instructions

If the user explicitly asks to connect or bind GovernLoop to a ChatGPT reviewer conversation:
  run: governloop setup --repo <owner/repo>
  use the existing setup wizard; do not invent a replacement menu.

For a normal governed task:
  1. Run: governloop doctor --task-id <task> --repo <owner/repo>
  2. Follow exactly the single top-level next_required_action or next_required_external_action.
  3. Reuse an already-verified Interactive Local task scope when present; do not create, rewrite, or broaden authority from inference.
  4. When reviewer_binding is the next action, run: governloop setup --repo <owner/repo>
  5. At a genuine pending REVIEW gate, use the existing GovernLoop review handoff path.

Never infer Ready, Merge, Release, or Deploy authority from task scope, review PASS, CI, runtime state, or relay ACK. Those remain separate explicit Product Owner decisions.

Principle: reuse existing GovernLoop mechanisms; no blocker evidence -> no new architecture; one blocker -> one minimal fix.
"""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["instructions"]:
        print(AGENT_INSTRUCTIONS, end="")
        return 0
    if args in (["-h"], ["--help"]):
        print("Coding agents: run `governloop instructions` first.\n")
    return runtime_cli.main(args)
