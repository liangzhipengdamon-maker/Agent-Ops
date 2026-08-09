#!/usr/bin/env python3
"""AGE-28 review result intake (GitHub PR review -> AgentOps decision).

Reads the authoritative GitHub PR review state (via `gh pr view --json`)
and parses it into an AgentOps review decision.

Governance boundaries:
- GitHub PR review is the SOURCE OF TRUTH.
- A review APPROVED/PASS is EVIDENCE, not authorization.
- The parser NEVER self-approves, never authorizes merge/deploy.
- Fail closed: unreadable or ambiguous state -> INCOMPLETE (wait), never
  a fabricated verdict.
"""

import dataclasses
import json
import subprocess
from typing import Dict, Optional


@dataclasses.dataclass(frozen=True)
class ReviewDecision:
    state: str            # APPROVED | CHANGES_REQUESTED | COMMENTED | INCOMPLETE | BLOCKED
    decision: str         # PASS | CHANGES_REQUESTED | COMMENTED | INCOMPLETE | BLOCKED
    repo: str
    pr: int
    head: str
    fail_closed: bool = False

    def __repr__(self):
        return (f"ReviewDecision(state={self.state}, decision={self.decision}, "
                f"repo={self.repo}, pr={self.pr}, head={self.head}, "
                f"fail_closed={self.fail_closed})")


def _parse_pr_json(raw: str) -> Dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def review_from_github(
    repo: str,
    pr: int,
    expected_head: str,
    pr_json: Optional[Dict] = None,
) -> ReviewDecision:
    """Build a ReviewDecision from a GitHub PR JSON object.

    `pr_json` fields expected:
      - reviewDecision: APPROVED | CHANGES_REQUESTED | REVIEW_REQUIRED | null
      - headRefOid: exact HEAD SHA
      - mergeable: MERGEABLE | CONFLICTING | UNKNOWN | null

    `expected_head` is the exact reviewed HEAD. If headRefOid !=
    expected_head, the review is stale -> INCOMPLETE (fail closed).
    """
    if pr_json is None:
        return ReviewDecision(
            state="INCOMPLETE", decision="INCOMPLETE",
            repo=repo, pr=pr, head=expected_head, fail_closed=True)

    head = pr_json.get("headRefOid") or ""
    if not head:
        return ReviewDecision(
            state="INCOMPLETE", decision="INCOMPLETE",
            repo=repo, pr=pr, head=expected_head, fail_closed=True)

    if head != expected_head:
        return ReviewDecision(
            state="INCOMPLETE", decision="INCOMPLETE",
            repo=repo, pr=pr, head=head, fail_closed=True)

    rd = pr_json.get("reviewDecision")
    mergeable = pr_json.get("mergeable")

    # Merge conflicts / unknown mergeability -> INCOMPLETE (wait), never
    # proceed.
    if mergeable in ("CONFLICTING", "UNKNOWN"):
        return ReviewDecision(
            state="INCOMPLETE", decision="INCOMPLETE",
            repo=repo, pr=pr, head=head, fail_closed=True)

    if rd == "APPROVED":
        return ReviewDecision(state="APPROVED", decision="PASS",
                              repo=repo, pr=pr, head=head)
    if rd == "CHANGES_REQUESTED":
        return ReviewDecision(state="CHANGES_REQUESTED", decision="CHANGES_REQUESTED",
                              repo=repo, pr=pr, head=head)
    if rd == "REVIEW_REQUIRED" or rd is None:
        return ReviewDecision(state="REVIEW_REQUIRED", decision="INCOMPLETE",
                              repo=repo, pr=pr, head=head, fail_closed=True)
    return ReviewDecision(state="INCOMPLETE", decision="INCOMPLETE",
                          repo=repo, pr=pr, head=head, fail_closed=True)


def read_github_pr(repo: str, pr: int, expected_head: str) -> ReviewDecision:
    """Read the authoritative PR review state via `gh pr view`.

    Fails closed if the command errors or the JSON is unreadable.
    """
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json", "reviewDecision,headRefOid,mergeable"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        pr_json = _parse_pr_json(res.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return ReviewDecision(state="INCOMPLETE", decision="INCOMPLETE",
                              repo=repo, pr=pr, head=expected_head, fail_closed=True)
    return review_from_github(repo, pr, expected_head, pr_json)
