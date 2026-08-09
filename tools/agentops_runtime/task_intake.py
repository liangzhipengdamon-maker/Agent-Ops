#!/usr/bin/env python3
"""AGE-27 task intake (Linear discovery -> notification).

Detects eligible tasks from a Linear issue list and writes
`TASK_DISCOVERED` notification records into a local intake queue.

Governance boundaries (AGE-27):
- The worker is discover + notify ONLY. It never claims, leases,
  executes, or decides.
- Notification is a pointer to the Linear issue (source of truth), not
  a copy of the task.
- Duplicate-claim prevention is delegated to LoopX lease (AGE-24 Phase 1),
  not implemented here.
"""

import dataclasses
import json
import os
import time
from typing import List, Optional


@dataclasses.dataclass(frozen=True)
class DiscoveredTask:
    linear_issue: str
    repo: str
    state: str
    discovered_at: str

    def to_record(self) -> dict:
        return {
            "type": "TASK_DISCOVERED",
            "linear_issue": self.linear_issue,
            "repo": self.repo,
            "state": self.state,
            "discovered_at": self.discovered_at,
        }


STARTABLE_STATES = {"Backlog", "Todo"}
NON_STARTABLE_STATES = {"Done", "Canceled", "In Progress", "In Review"}


def is_eligible(issue: dict, repo: str) -> bool:
    """An issue is eligible when:
      - it belongs to an authorized repo/project,
      - it is in a startable state,
      - it has a non-empty title/description (machine-readable objective).
    """
    state = (issue.get("state") or "").strip()
    title = (issue.get("title") or "").strip()
    if state not in STARTABLE_STATES:
        return False
    if not title:
        return False
    if not repo:
        return False
    return True


def discover(issues: List[dict], repo: str) -> List[DiscoveredTask]:
    """Filter eligible issues and produce discovery notifications."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    out = []
    for issue in issues:
        if is_eligible(issue, repo):
            out.append(DiscoveredTask(
                linear_issue=issue.get("id") or issue.get("identifier") or "",
                repo=repo,
                state=issue.get("state") or "",
                discovered_at=now,
            ))
    return out


def write_discovery_records(tasks: List[DiscoveredTask], queue_dir: str) -> List[str]:
    """Write one JSON record per discovered task into the intake queue.

    Returns the list of written file paths.
    """
    os.makedirs(queue_dir, exist_ok=True)
    written = []
    for task in tasks:
        safe_id = task.linear_issue.replace("/", "_").replace(":", "_")
        path = os.path.join(queue_dir, f"{safe_id}.json")
        with open(path, "w") as f:
            json.dump(task.to_record(), f, indent=2)
        written.append(path)
    return written
