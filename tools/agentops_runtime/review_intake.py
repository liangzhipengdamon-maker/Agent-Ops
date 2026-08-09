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


def _review_binds_head(r: dict, expected_head: str) -> bool:
    """A review binds the exact current HEAD via its submitted commit_id
    (authoritative) or a body `HEAD:` line. Both are used because the GPT
    same-owner path posts a formal COMMENTED review whose body carries the
    HEAD marker, while native GitHub reviews carry commit_id."""
    commit = (r.get("commit_id") or "").lower()
    if commit and commit == expected_head.lower():
        return True
    m = re.search(r"HEAD:\s*(\S+)", r.get("body") or "")
    return bool(m) and m.group(1).strip().lower() == expected_head.lower()


def _review_has_any_binding(r: dict) -> bool:
    """True if the review exposes any HEAD binding (commit_id or body HEAD:).
    P0-2: a formal review with NO binding is missing/ambiguous -> the
    executable signal is INCOMPLETE, never applied."""
    if (r.get("commit_id") or "").strip():
        return True
    return bool(re.search(r"HEAD:\s*(\S+)", r.get("body") or ""))


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
    # CHANGES_REQUESTED. A formal review without any HEAD binding is
    # missing/ambiguous -> INCOMPLETE (fail closed). A formal review bound to
    # a DIFFERENT HEAD is stale -> skip; with no current-HEAD verdict the
    # outcome is INCOMPLETE, never the stale one.
    for r in reviews:
        body = r.get("body") or ""
        if r.get("state") != "COMMENTED" or "AGENTOPS_REVIEW" not in body:
            continue
        if not _review_has_any_binding(r):
            return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                                 [], fail_closed=True)
        if not _review_binds_head(r, expected_head):
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
    # approves/changes on GitHub directly). Only a native verdict whose
    # review is bound to THIS exact HEAD is executable; a stale native
    # review for an older HEAD is INCOMPLETE.
    if rd == "APPROVED" and mergeable in ("MERGEABLE", None):
        if any(r.get("state") == "APPROVED"
               and _review_binds_head(r, expected_head) for r in reviews):
            return ReviewOutcome("APPROVED", "PASS", repo, pr, head, [])
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    if rd == "CHANGES_REQUESTED":
        findings = []
        bound = False
        for r in reviews:
            if r.get("state") == "CHANGES_REQUESTED" and r.get("body"):
                if _review_binds_head(r, expected_head):
                    bound = True
                    findings.append(r["body"])
        if bound and findings:
            return ReviewOutcome("CHANGES_REQUESTED", "CHANGES_REQUESTED",
                                 repo, pr, head, findings)
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    if mergeable in ("CONFLICTING", "UNKNOWN"):
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    # No executable PASS / CHANGES_REQUESTED verdict bound to this HEAD:
    # incomplete review evidence, fail closed.
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
