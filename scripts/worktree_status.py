#!/usr/bin/env python3
"""GovernLoop worktree status helper.

Reads `git worktree list --porcelain` and prints a concise status for every
worktree attached to the current repository: path, branch, HEAD, and whether
the working tree is clean or dirty.

Read-only helper. It never removes worktrees, never deletes branches, and
makes no GitHub mutations.
"""

import argparse
import os
import subprocess
import sys


def run_git(args, cwd=None):
    """Run a git command and return its stdout, or None on failure."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def parse_porcelain(text):
    """Parse `git worktree list --porcelain` output into a list of records.

    Each record is a dict with keys: path, head, branch (may be None for
    detached worktrees).
    """
    worktrees = []
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current is not None:
                worktrees.append(current)
                current = None
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current = {"path": value, "head": None, "branch": None}
        elif key == "HEAD":
            if current is not None:
                current["head"] = value
        elif key == "branch":
            if current is not None:
                current["branch"] = value
    if current is not None:
        worktrees.append(current)
    return worktrees


def has_tracked_changes(status_lines):
    """Return True if status porcelain output has tracked modifications.

    Untracked files (lines starting with `??`) are ignored: they are not
    tracked-tree dirt.
    """
    return any(not line.startswith("??") for line in status_lines)


def is_clean(path):
    """Return True if the worktree has no tracked modifications."""
    out = run_git(["status", "--porcelain"], cwd=path)
    if out is None:
        return None
    return not has_tracked_changes(out.splitlines())


def fmt_head(sha):
    return sha[:12] if sha else "(none)"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List GovernLoop worktrees with branch, HEAD, and status."
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Path to the repository (defaults to the current directory).",
    )
    args = parser.parse_args(argv)

    repo = args.repo or os.getcwd()
    text = run_git(["worktree", "list", "--porcelain"], cwd=repo)
    if text is None:
        print(f"error: unable to read worktree list in {repo}", file=sys.stderr)
        return 1

    worktrees = parse_porcelain(text)
    if not worktrees:
        print("No worktrees found.")
        return 0

    for wt in worktrees:
        branch = wt["branch"] or "(detached)"
        state = is_clean(wt["path"])
        if state is None:
            status = "unknown"
        elif state:
            status = "clean"
        else:
            status = "dirty"
        print(
            f"{wt['path']}\t{branch}\t{fmt_head(wt['head'])}\t{status}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
