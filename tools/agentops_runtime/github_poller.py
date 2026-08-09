#!/usr/bin/env python3
"""AGE-30 GitHub real-state poller.

Reads the CURRENT real PR/HEAD/review/mergeable/status state via `gh`.
It is read-only and authoritative: it does not mutate GitHub and does not
invent state. Returns None on any failure (fail closed).

The watcher uses this to detect real change and only trigger downstream
processing when the snapshot actually differs.
"""

import json
import subprocess
from typing import Optional


def read_pr_state(repo: str, pr) -> Optional[dict]:
    """Read real GitHub PR state.

    Fields: state, headRefOid, reviewDecision, mergeable, updatedAt.
    Returns None if `gh` fails (fail closed).
    """
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json", "state,headRefOid,reviewDecision,mergeable,updatedAt"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        data = json.loads(res.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            OSError, json.JSONDecodeError):
        return None
    return {
        "state": data.get("state"),
        "head": data.get("headRefOid"),
        "review_decision": data.get("reviewDecision"),
        "mergeable": data.get("mergeable"),
        "updated_at": data.get("updatedAt"),
    }


def read_pr_head(repo: str, pr) -> Optional[str]:
    """Read the current real PR HEAD SHA. None on failure."""
    snap = read_pr_state(repo, pr)
    return snap.get("head") if snap else None
