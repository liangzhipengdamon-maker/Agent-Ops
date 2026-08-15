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
import tempfile
from urllib.parse import urlparse

from . import __main__ as runtime_cli


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SCP_GITHUB_RE = re.compile(
    r"^(?:git@)?github\.com:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$",
    re.IGNORECASE,
)
_HOST_CONFIRM_FLAG = "--host-confirm"
_HOST_CONFIRM_TRANSPORT = "host_explicit_confirm_v1"


AGENT_INSTRUCTIONS = """GovernLoop Agent Instructions

For a normal coding task, the user should only need to say: Use GovernLoop for this task.

A. Normal governed task
  1. From the target Git repository/worktree, immediately run: governloop start
  2. GovernLoop resolves owner/repo from the current Git origin. Do not ask the user for the repo when it is already resolvable.
  3. If start returns TASK_ID_REQUIRED, use the existing task ID already present in the task/context and rerun: governloop start --task-id <task>
  4. If no task ID exists in the task/context, ask the user only for that missing task ID. Do not invent one from a branch name, commit, issue text, or guess.
  5. Follow exactly the single NEXT_REQUIRED_ACTION / next_required_action / next_required_external_action returned by GovernLoop. Do not preflight hypothetical later blockers.
  6. If the next action is `setup-task-scope`, present the exact scope in the host interaction. After the user explicitly approves that exact scope in the coding-agent host, rerun the same command with `--host-confirm`. Do not require a separate Terminal TTY.
  7. At a genuine pending REVIEW gate, use the existing GovernLoop review handoff path.

B. Explicit reviewer connection request
  1. From the target Git repository/worktree, immediately run: governloop setup
  2. GovernLoop resolves owner/repo from the current Git origin and owns the dedicated browser runtime and setup wizard.
  3. Do NOT preflight or invent Chrome commands, CDP ports, browser profiles, setup-server ports, relay/config paths, source-code investigation, doctor checks, Linear checks, or authority checks first.
  4. If setup returns NEXT_REQUIRED_ACTION, address exactly that one blocker and rerun the same setup command.
  5. Do NOT ask the user for the ChatGPT conversation URL in Agent chat before setup reaches its wizard. The existing setup wizard owns that input.
  6. In the wizard, the user's actions are limited to signing in/opening the exact ChatGPT reviewer conversation if needed, pasting its https://chatgpt.com/c/... URL, Test Connection, and Bind Conversation.

Interactive Local remains a same-user/same-uid trust boundary. `--host-confirm` records host-confirm provenance; it is not signed authority and never grants lifecycle permission.
Never infer Ready, Merge, Release, or Deploy authority from task scope, review PASS, CI, runtime state, setup success, host confirmation, or relay ACK. Those remain separate explicit Product Owner decisions.

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
    if parsed.query or parsed.fragment or parsed.params:
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
    if "-h" in args or "--help" in args or "--repo" in args:
        return runtime_cli.main(args)
    repo, error = _detect_current_repo()
    if not repo:
        return _print_start_blocker(
            "REPOSITORY_UNRESOLVED",
            error or "repository could not be resolved",
            "run `governloop setup` from the target GitHub repository/worktree",
        )
    return runtime_cli.main([args[0], "--repo", repo, *args[1:]])


class _HostConfirmedInput:
    """One-shot stdin used only after the host-confirm flag is explicit."""

    def isatty(self):
        return True

    def readline(self, *args, **kwargs):
        return "YES\n"


class _TtyOutputProxy:
    """Pass output through while satisfying the legacy TTY precondition."""

    def __init__(self, stream):
        self._stream = stream

    def isatty(self):
        return True

    def write(self, value):
        return self._stream.write(value)

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _arg_value(args: list[str], name: str) -> str | None:
    try:
        index = args.index(name)
    except ValueError:
        return None
    if index + 1 >= len(args):
        return None
    return args[index + 1]


def _record_host_confirm_provenance(task_id: str) -> None:
    """Add truthful host-confirm provenance without changing scope semantics."""
    path = runtime_cli.authority.task_scope_path(task_id)
    if path is None or not path.exists():
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            return
        doc["confirmation_transport"] = _HOST_CONFIRM_TRANSPORT
        doc["integrity_sha256"] = runtime_cli.authority._task_scope_integrity(doc)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, indent=2, sort_keys=True, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            os.chmod(path, 0o600)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except (OSError, json.JSONDecodeError):
        return


def _setup_task_scope_with_host_confirm(args: list[str]) -> int:
    """Reuse the canonical task-scope writer from a coding-agent host shell.

    Interactive Local is already same-user/same-uid and its confirmation marker
    is provenance only. This explicit flag removes only the TTY transport
    requirement; validation, allowed operations, write/verify, and lifecycle
    boundaries remain in the canonical runtime implementation.
    """
    if _HOST_CONFIRM_FLAG not in args:
        return runtime_cli.main(args)

    delegated = [value for value in args if value != _HOST_CONFIRM_FLAG]
    task_id = _arg_value(delegated, "--task-id")
    target = None
    existed_before = False
    if task_id:
        try:
            target = runtime_cli.authority.task_scope_path(task_id)
            existed_before = bool(target and target.exists())
        except ValueError:
            pass

    original_stdin = sys.stdin
    original_stdout = sys.stdout
    try:
        sys.stdin = _HostConfirmedInput()
        sys.stdout = _TtyOutputProxy(original_stdout)
        rc = runtime_cli.main(delegated)
    finally:
        sys.stdin = original_stdin
        sys.stdout = original_stdout

    wrote_scope = rc == 0 and task_id and (not existed_before or "--replace" in delegated)
    if wrote_scope:
        _record_host_confirm_provenance(task_id)
        verified = runtime_cli.authority.verify_task_scope(
            task_id, expected_repo=_arg_value(delegated, "--repo"))
        if not verified.get("ok"):
            print(json.dumps({
                "status": "HOST_CONFIRM_PROVENANCE_VERIFY_FAILED",
                "task_id": task_id,
                "detail": verified.get("detail"),
            }, indent=2, ensure_ascii=False))
            return 7
        print(json.dumps({
            "status": "HOST_CONFIRM_RECORDED",
            "task_id": task_id,
            "confirmation_transport": _HOST_CONFIRM_TRANSPORT,
            "trust_boundary": "same-user / same-uid; provenance only",
            "lifecycle_authority_granted": False,
        }, indent=2, ensure_ascii=False))
    return rc


def _print_agent_help() -> None:
    print("GovernLoop coding-agent entrypoints:")
    print("  governloop start          use GovernLoop for the current task/repository")
    print("  governloop setup          connect the current repository to a ChatGPT reviewer")
    print("  governloop instructions   print canonical agent operating instructions")
    print()
    print("Advanced/runtime commands:")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _print_agent_help()
        print("Run `governloop --help` for the full command list.")
        return 0
    if args == ["instructions"]:
        print(AGENT_INSTRUCTIONS, end="")
        return 0
    if args and args[0] == "start":
        return _cmd_start(args[1:])
    if args and args[0] == "setup":
        return _setup_with_detected_repo(args)
    if args and args[0] == "setup-task-scope":
        if args[1:] in (["-h"], ["--help"]):
            print("Host-confirm option: --host-confirm (use only after explicit user approval in the coding-agent host).")
        return _setup_task_scope_with_host_confirm(args)
    if args in (["-h"], ["--help"]):
        _print_agent_help()
    return runtime_cli.main(args)
