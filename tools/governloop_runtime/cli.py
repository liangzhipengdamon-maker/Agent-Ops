"""Thin public CLI wrapper for fresh-agent discoverability.

All existing GovernLoop commands are delegated unchanged to the canonical
runtime CLI. This wrapper owns only the read-only `instructions` discovery
entry and one help hint for coding agents.
"""

from __future__ import annotations

import sys

from . import __main__ as runtime_cli


AGENT_INSTRUCTIONS = """GovernLoop Agent Instructions

Choose the path from the user's intent. Do not mix the two paths.

A. If the user explicitly asks to connect or bind GovernLoop to a ChatGPT reviewer conversation:
  1. Determine only the target repository (owner/repo). If it is already clear, do not ask again.
  2. Immediately run: governloop setup --repo <owner/repo>
  3. Do NOT preflight or invent Chrome commands, CDP ports, browser profiles, setup-server ports, relay/config paths, source-code investigation, doctor checks, Linear checks, or authority checks first.
  4. GovernLoop setup owns the dedicated browser runtime and setup wizard. Let setup report the first real blocker.
  5. If setup returns NEXT_REQUIRED_ACTION, address exactly that one blocker and rerun the same setup command. Do not solve later or hypothetical blockers.
  6. In the wizard, the user's actions are limited to signing in/opening the exact ChatGPT reviewer conversation if needed, pasting its https://chatgpt.com/c/... URL, Test Connection, and Bind Conversation.

B. For a normal governed task (not an explicit reviewer-connection request):
  1. Run: governloop doctor --task-id <task> --repo <owner/repo>
  2. Follow exactly the single top-level next_required_action or next_required_external_action.
  3. Reuse an already-verified Interactive Local task scope when present; do not create, rewrite, or broaden authority from inference.
  4. When reviewer_binding is the next action, run: governloop setup --repo <owner/repo>
  5. At a genuine pending REVIEW gate, use the existing GovernLoop review handoff path.

Never infer Ready, Merge, Release, or Deploy authority from task scope, review PASS, CI, runtime state, setup success, or relay ACK. Those remain separate explicit Product Owner decisions.

Principle: no blocker evidence -> no speculative step; one real blocker -> one next action; reuse existing GovernLoop mechanisms before adding or inventing anything.
"""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["instructions"]:
        print(AGENT_INSTRUCTIONS, end="")
        return 0
    if args in (["-h"], ["--help"]):
        print("Coding agents: run `governloop instructions` first.\n")
    return runtime_cli.main(args)
