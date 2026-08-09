#!/usr/bin/env python3
"""AGE-30 review intake: real GitHub PR review bound to exact PR+HEAD.

Reads the authoritative GitHub PR review state via `gh` and classifies it
into an AgentOps review outcome:
  - PASS               -> reviewApproved (APPROVED, mergeable, head match)
  - CHANGES_REQUESTED  -> GitHub CHANGES_REQUESTED
  - NOT_PASS           -> COMMENTED with explicit "NOT PASS" / "NOT_PASS"
                          in review bodies, or blocked, or incomplete
                          evidence (fail closed)

The outcome is bound to the exact current PR + HEAD; a stale HEAD is
INCOMPLETE (fail closed). NEVER self-approves.
"""

import dataclasses
import json
import re
import subprocess
from typing import Optional


@dataclasses.dataclass(frozen=True)
class ReviewOutcome:
    state: str            # APPROVED | CHANGES_REQUESTED | COMMENTED | INCOMPLETE
    decision: str         # PASS | CHANGES_REQUESTED | NOT_PASS | INCOMPLETE
    repo: str
    pr: int
    head: str
    findings: list
    fail_closed: bool = False

    def __repr__(self):
        return (f"ReviewOutcome(state={self.state}, decision={self.decision}, "
                f"repo={self.repo}, pr={self.pr}, head={self.head}, "
                f"fail_closed={self.fail_closed})")


def _parse_pr_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def review_from_github(repo: str, pr: int, expected_head: str,
                       pr_json: Optional[dict] = None) -> ReviewOutcome:
    if pr_json is None:
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr,
                             expected_head, [], fail_closed=True)

    head = pr_json.get("headRefOid") or ""
    if not head:
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr,
                             expected_head, [], fail_closed=True)
    if head != expected_head:
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    rd = pr_json.get("reviewDecision")
    mergeable = pr_json.get("mergeable")
    reviews = pr_json.get("reviews") or []

    # P0-3: the same-owner GPT review path posts a formal COMMENTED review
    # carrying a machine-readable AGENTOPS_REVIEW verdict bound to the exact
    # HEAD. Parse that formal verdict for BOTH PASS and NOT_PASS /
    # CHANGES_REQUESTED. A COMMENTED review that names a DIFFERENT HEAD is
    # stale and must be INCOMPLETE (fail closed), never applied.
    for r in reviews:
        body = r.get("body") or ""
        if r.get("state") != "COMMENTED" or "AGENTOPS_REVIEW" not in body:
            continue
        # The formal review MUST name this exact HEAD. A HEAD line that names
        # a different HEAD (even a non-hex placeholder) is stale -> skip.
        m_head = re.search(r"HEAD:\s*(\S+)", body)
        if m_head:
            head_val = m_head.group(1).strip().lower()
            if head_val != expected_head.lower():
                continue  # stale review for another HEAD; ignore
        m_verdict = re.search(
            r"\b(PASS|NOT_PASS|CHANGES_REQUESTED)\b", body, re.IGNORECASE)
        if m_verdict:
            verdict = m_verdict.group(1).upper()
            if verdict == "PASS":
                return ReviewOutcome("COMMENTED", "PASS", repo, pr, head,
                                     [body])
            return ReviewOutcome("COMMENTED", verdict, repo, pr, head,
                                 [body])

    # GitHub native reviewDecision (used when an independent reviewer
    # approves/changes on GitHub directly).
    if rd == "APPROVED" and mergeable in ("MERGEABLE", None):
        return ReviewOutcome("APPROVED", "PASS", repo, pr, head, [])

    if rd == "CHANGES_REQUESTED":
        findings = []
        for r in reviews:
            if r.get("state") == "CHANGES_REQUESTED" and r.get("body"):
                findings.append(r["body"])
        return ReviewOutcome("CHANGES_REQUESTED", "CHANGES_REQUESTED",
                             repo, pr, head, findings)

    # COMMENTED reviews with explicit NOT_PASS / NOT PASS signal a blocker.
    not_pass_findings = []
    for r in reviews:
        body = r.get("body") or ""
        if r.get("state") == "COMMENTED" and re.search(
                r"\bNOT\s*PASS\b|\bNOT_PASS\b", body, re.IGNORECASE):
            not_pass_findings.append(body)
    if not_pass_findings:
        return ReviewOutcome("COMMENTED", "NOT_PASS", repo, pr, head,
                             not_pass_findings)

    if mergeable in ("CONFLICTING", "UNKNOWN"):
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    # No PASS / CHANGES_REQUESTED / NOT_PASS: incomplete review evidence.
    return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                         [], fail_closed=True)


def read_github_pr(repo: str, pr: int, expected_head: str) -> ReviewOutcome:
    """Read the authoritative PR review state via `gh` (incl. reviews)."""
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json",
             "reviewDecision,headRefOid,mergeable,state,reviews,updatedAt"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        pr_json = _parse_pr_json(res.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr,
                             expected_head, [], fail_closed=True)
    return review_from_github(repo, pr, expected_head, pr_json)


def read_pr_head(repo: str, pr: int) -> Optional[str]:
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json", "headRefOid"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return (json.loads(res.stdout) or {}).get("headRefOid") or None
    except Exception:
        return None
