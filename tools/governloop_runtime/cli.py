"""Thin public CLI wrapper for fresh-agent discoverability.

All existing GovernLoop commands are delegated unchanged to the canonical
runtime CLI. This wrapper owns only agent-facing discovery conveniences:
``instructions``, ``start``, repository auto-detection, and the top-level help
hint. It does not create a second authority, setup, review, or lifecycle path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlparse

from . import __main__ as runtime_cli


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SCP_GITHUB_RE = re.compile(
    r"^(?:git@)?github\.com:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$",
    re.IGNORECASE,
)


AGENT_INSTRUCTIONS = """GovernLoop Agent Instructions

For a normal coding task, the user should only need to say: Use GovernLoop for this task.

A. Normal governed task
  1. From the target Git repository/worktree, immediately run: governloop start
  2. GovernLoop resolves owner/repo from the current Git origin. Do not ask the user for the repo when it is already resolvable.
  3. If start returns TASK_ID_REQUIRED, use the existing task ID already present in the task/context and rerun: governloop start --task-id <task>
  4. If no task ID exists in the task/context, ask the user only for that missing task ID. Do not invent one from a branch name, commit, issue text, or guess.
  5. Follow exactly the single NEXT_REQUIRED_ACTION / next_required_action / next_required_external_action returned by GovernLoop. Do not preflight hypothetical later blockers.
  6. At a genuine pending REVIEW gate, use the existing GovernLoop review handoff path.

B. Explicit reviewer connection request
  1. From the target Git repository/worktree, immediately run: governloop setup
  2. GovernLoop resolves owner/repo from the current Git origin and owns the dedicated browser runtime and setup wizard.
  3. Do NOT preflight or invent Chrome commands, CDP ports, browser profiles, setup-server ports, relay/config paths, source-code investigation, doctor checks, Linear checks, or authority checks first.
  4. If setup returns NEXT_REQUIRED_ACTION, address exactly that one blocker and rerun the same setup command.
  5. In the wizard, the user's actions are limited to signing in/opening the exact ChatGPT reviewer conversation if needed, pasting its https://chatgpt.com/c/... URL, Test Connection, and Bind Conversation.

Never infer Ready, Merge, Release, or Deploy authority from task scope, review PASS, CI, runtime state, setup success, or relay ACK. Those remain separate explicit Product Owner decisions.

Principle: user states intent; GovernLoop discovers local context; missing information is requested one item at a time; no blocker evidence -> no speculative step.
"""


def _normalize_repo(value: str | None) -> str | None:
    raw = (value or "").strip()
    if raw.endswith(".git"):
        raw = raw[:-4]
    return raw if _REPO_RE.fullmatch(raw) else None


def _repo_from_origin(origin: str | None) -> str | None:
    """Return owner/repo for ordinary GitHub HTTPS/SSH origins, else None."""
    raw = (origin or "").strip()
    if not raw:
        return None

    match = _SCP_GITHUB_RE.fullmatch(raw)
    if match:
        return _normalize_repo(match.group(1))

    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in ("https", "ssh"):
        return None
    if (parsed.hostname or "").lower() != "github.com":
        return None
    if parsed.scheme == "ssh" and parsed.username not in (None, "git"):
        return None
    path = (parsed.path or "").strip("/")
    return _normalize_repo(path)


def _detect_current_repo(cwd: str | None = None) -> tuple[str | None, str | None]:
    """Resolve the current repository from git remote.origin.url without shell use."""
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not read git origin: {exc}"
    if result.returncode != 0:
        return None, "current directory is not a Git repository with remote.origin.url"
    origin = (result.stdout or "").strip()
    repo = _repo_from_origin(origin)
    if not repo:
        return None, f"unsupported or ambiguous GitHub origin: {origin!r}"
    return repo, None


def _print_start_blocker(code: str, detail: str, next_action: str, repo: str | None = None) -> int:
    payload = {
        "status": "START_BLOCKED",
        "blocker": code,
        "detail": detail,
        "NEXT_REQUIRED_ACTION": next_action,
    }
    if repo:
        payload["repo"] = repo
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 2


def _start_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="governloop start",
        description="Start GovernLoop for the current GitHub repository without manually supplying repo.",
    )
    parser.add_argument("--task-id", help="existing GovernLoop/Linear task ID; never inferred")
    parser.add_argument("--pr", type=int, help="optional existing pull request number")
    parser.add_argument("--repo", help=argparse.SUPPRESS)
    return parser


def _cmd_start(args: list[str]) -> int:
    parsed = _start_parser().parse_args(args)
    repo = _normalize_repo(parsed.repo) if parsed.repo else None
    if parsed.repo and not repo:
        return _print_start_blocker(
            "REPOSITORY_INVALID",
            "explicit --repo must be in owner/repository form",
            "rerun `governloop start` from the target Git repository without --repo",
        )
    if not repo:
        repo, error = _detect_current_repo()
        if not repo:
            return _print_start_blocker(
                "REPOSITORY_UNRESOLVED",
                error or "repository could not be resolved",
                "run `governloop start` from the target GitHub repository/worktree",
            )

    task_id = (parsed.task_id or "").strip()
    if not task_id:
        return _print_start_blocker(
            "TASK_ID_REQUIRED",
            "GovernLoop will not invent or infer a task ID",
            "rerun `governloop start --task-id <existing-task-id>`; if no task ID exists in the current task/context, ask the user only for that ID",
            repo=repo,
        )

    delegated = ["doctor", "--task-id", task_id, "--repo", repo]
    if parsed.pr is not None:
        delegated.extend(["--pr", str(parsed.pr)])
    return runtime_cli.main(delegated)


def _setup_with_detected_repo(args: list[str]) -> int:
    """Allow agent-facing `governloop setup` to resolve repo from current worktree."""
    if "--repo" in args:
        return runtime_cli.main(args)
    repo, error = _detect_current_repo()
    if not repo:
        return _print_start_blocker(
            "REPOSITORY_UNRESOLVED",
            error or "repository could not be resolved",
            "run `governloop setup` from the target GitHub repository/worktree",
        )
    return runtime_cli.main([args[0], "--repo", repo, *args[1:]])


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["instructions"]:
        print(AGENT_INSTRUCTIONS, end="")
        return 0
    if args and args[0] == "start":
        return _cmd_start(args[1:])
    if args and args[0] == "setup":
        return _setup_with_detected_repo(args)
    if args in (["-h"], ["--help"]):
        print("Coding agents: run `governloop start` in the target repository.\n")
        print("Explicit reviewer connection: run `governloop setup` in the target repository.\n")
    return runtime_cli.main(args)
