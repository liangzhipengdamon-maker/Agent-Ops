#!/usr/bin/env python3
"""AGE-30 review intake: real GitHub PR review bound to exact PR+HEAD.

Reads the authoritative GitHub PR review state via ``gh`` and classifies it
into a GovernLoop review outcome:
  - PASS               -> formal GOV​ERNLOOP_REVIEW PASS at the exact HEAD,
                          legacy AGENTOPS_REVIEW PASS, or native APPROVED
  - CHANGES_REQUESTED  -> canonical/legacy formal CHANGES_REQUESTED at the
                          exact HEAD, or native CHANGES_REQUESTED bound to it
  - NOT_PASS           -> canonical/legacy formal NOT_PASS at the exact HEAD
  - INCOMPLETE         -> no executable verdict bound to the exact current
                          HEAD, including ambiguous/duplicate formal markers

``GOVERNLOOP_REVIEW`` is canonical. ``AGENTOPS_REVIEW`` remains a pre-v0.1
compatibility marker. The outcome is bound to the exact current PR + HEAD; a
stale HEAD is INCOMPLETE (fail closed). NEVER self-approves. Among multiple
current-HEAD formal review submissions the LATEST (by submittedAt) wins, but
an ambiguous latest formal submission fails closed rather than falling back.
"""

import dataclasses
import json
import os
import re
import subprocess
from typing import Optional

from .review_protocol import (
    has_formal_review_marker,
    parse_formal_review_verdict,
)


def _profile_path() -> Optional[str]:
    """Locate profiles/agentops.json from the repo root (walk up from CWD or
    the module location)."""
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    for base in (pathlib.Path.cwd(), here, here.parent, here.parent.parent,
                 here.parent.parent.parent):
        p = base / "profiles" / "agentops.json"
        if p.exists():
            return str(p)
    return None


def trusted_reviewers() -> set:
    """Configured trusted reviewer/PO identities (exact GitHub logins).

    Source: AGENTOPS_TRUSTED_REVIEWERS env (canonical GOV​ERNLOOP_* is mapped
    by the compatibility facade), else the project profile
    governance.trusted_reviewers. An EMPTY set fails closed: no review/PO
    signal is executable. R6-P0-1: executable control signals are trusted-
    author bound; an untrusted account cannot inject PASS /
    CHANGES_REQUESTED / PO decision into the control loop.
    """
    env = os.environ.get("AGENTOPS_TRUSTED_REVIEWERS", "").strip()
    if env:
        return {x.strip() for x in env.split(",") if x.strip()}
    path = _profile_path()
    if not path:
        return set()
    try:
        with open(path) as f:
            prof = json.load(f)
        return set((prof.get("governance") or {})
                   .get("trusted_reviewers") or [])
    except (OSError, json.JSONDecodeError):
        return set()


def _author_trusted(r: dict) -> bool:
    """True when the review's submitting identity is in the trusted set.
    Missing author -> untrusted (fail closed)."""
    login = ((r.get("author") or {}).get("login") or "").strip()
    return bool(login) and login in trusted_reviewers()


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
    """A review binds the exact current HEAD via its submitted commit (the
    authoritative ``commit.oid``; also accept a top-level ``commit_id`` for
    callers/tests) or a body ``HEAD:`` line. Both are used because the GPT
    same-owner path posts a formal COMMENTED review whose body carries the
    HEAD marker, while native GitHub reviews carry the commit oid."""
    commit = (r.get("commit_id") or "").lower()
    if not commit:
        commit = ((r.get("commit") or {}).get("oid") or "").lower()
    if commit and commit == expected_head.lower():
        return True
    m = re.search(r"HEAD:\s*(\S+)", r.get("body") or "")
    return bool(m) and m.group(1).strip().lower() == expected_head.lower()


def _review_has_any_binding(r: dict) -> bool:
    """True if the review exposes any HEAD binding (commit oid/id or body
    HEAD:). A formal review with NO binding is missing/ambiguous and must not
    become executable."""
    commit = (r.get("commit_id") or "").strip()
    if not commit:
        commit = ((r.get("commit") or {}).get("oid") or "").strip()
    if commit:
        return True
    return bool(re.search(r"HEAD:\s*(\S+)", r.get("body") or ""))


def _latest_bound_review(reviews, expected_head: str):
    """Select the latest current-HEAD TRUSTED formal review submission.

    Both the canonical GOV​ERNLOOP_REVIEW marker and the legacy
    AGENTOPS_REVIEW marker identify a formal submission. Marker validity is
    evaluated only after latest selection so a newer ambiguous/invalid formal
    review fails closed instead of silently falling back to an older PASS.
    """
    bound = [r for r in reviews
             if r.get("state") == "COMMENTED"
             and has_formal_review_marker(r.get("body") or "")
             and _author_trusted(r)
             and _review_binds_head(r, expected_head)]
    if not bound:
        return None
    bound.sort(key=lambda r: (r.get("submittedAt") or "",
                              str(r.get("id") or "")), reverse=True)
    return bound[0]


def _any_trusted_formal(reviews) -> bool:
    """Any canonical/legacy formal review marker from a trusted author."""
    return any(has_formal_review_marker(r.get("body") or "")
               and _author_trusted(r) for r in reviews)


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

    # Same-owner GPT review path posts a formal COMMENTED review carrying a
    # machine-readable canonical/legacy verdict bound to the exact HEAD.
    # Select the latest bound trusted formal submission first, then require
    # EXACTLY one recognized marker line and a valid verdict. Duplicate or
    # mixed marker lines are INCOMPLETE (fail closed).
    latest = _latest_bound_review(reviews, expected_head)
    if latest is not None:
        body = latest.get("body") or ""
        formal = parse_formal_review_verdict(body)
        if formal.status != "VALID":
            return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                                 [], fail_closed=True)
        verdict = formal.verdict
        if verdict == "PASS":
            return ReviewOutcome("COMMENTED", "PASS", repo, pr, head,
                                 [body])
        return ReviewOutcome("COMMENTED", verdict, repo, pr, head, [body])

    # A trusted formal review exists but none binds this exact HEAD:
    # stale/missing/ambiguous -> fail closed.
    if _any_trusted_formal(reviews):
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    # GitHub native reviewDecision (used when an independent reviewer
    # approves/changes on GitHub directly). Only a native verdict whose
    # review is from a TRUSTED author AND bound to THIS exact HEAD is
    # executable; a stale or untrusted native review is INCOMPLETE.
    if rd == "APPROVED" and mergeable in ("MERGEABLE", None):
        if any(r.get("state") == "APPROVED" and _author_trusted(r)
               and _review_binds_head(r, expected_head) for r in reviews):
            return ReviewOutcome("APPROVED", "PASS", repo, pr, head, [])
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    if rd == "CHANGES_REQUESTED":
        findings = []
        bound = False
        for r in reviews:
            if r.get("state") == "CHANGES_REQUESTED" and r.get("body"):
                if _author_trusted(r) and _review_binds_head(r, expected_head):
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
    """Read the authoritative PR review state via ``gh`` (incl. reviews)."""
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
