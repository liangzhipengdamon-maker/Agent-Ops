#!/usr/bin/env python3
"""GitHub review intake bound to exact request + PR + HEAD.

The executable/live entrypoint is ``read_github_pr``. For formal machine
COMMENT reviews it always supplies an active request id (or explicit empty
sentinel), so missing/mismatched REVIEW_REQUEST_ID / REPO / PR / HEAD fails
closed. ``review_from_github`` can still be used as a structural unit-test
helper when ``expected_request_id`` is omitted; that helper-only mode is not
used by the live runtime.

Executable reviewer identity is projected only from externally verified
operator authority. Mutable repository profiles are never an authority source.
"""

import dataclasses
import json
import os
import re
import subprocess
from typing import Optional

from .review_protocol import has_formal_review_marker, parse_formal_review_verdict


def trusted_reviewers() -> set:
    """Return externally verified trusted reviewer identities only.

    ``AGENTOPS_TRUSTED_REVIEWERS`` is a compatibility projection written by
    GovernLoop only after external operator authority verification. The
    companion verification flag must be present. There is deliberately NO
    fallback to profiles/agentops.json or any other mutable repository file.
    Empty/unverified input fails closed.
    """
    if os.environ.get("AGENTOPS_AUTHORITY_VERIFIED", "") != "1":
        return set()
    env = os.environ.get("AGENTOPS_TRUSTED_REVIEWERS", "").strip()
    if not env:
        return set()
    return {x.strip() for x in env.split(",") if x.strip()}


def _author_trusted(review: dict) -> bool:
    login = ((review.get("author") or {}).get("login") or "").strip()
    return bool(login) and login in trusted_reviewers()


@dataclasses.dataclass(frozen=True)
class ReviewOutcome:
    state: str
    decision: str
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


def _review_binds_head(review: dict, expected_head: str) -> bool:
    commit = (review.get("commit_id") or "").lower()
    if not commit:
        commit = ((review.get("commit") or {}).get("oid") or "").lower()
    if commit and commit == expected_head.lower():
        return True
    match = re.search(r"^HEAD:\s*(\S+)\s*$", review.get("body") or "",
                      re.MULTILINE)
    return bool(match) and match.group(1).strip().lower() == expected_head.lower()


def _bridge_dir() -> str:
    return os.environ.get("AGENT_BRIDGE_DIR", ".agent-bridge")


def _request_marker_path(pr: int, head: str) -> str:
    return os.path.join(_bridge_dir(), f"review_request_{pr}_{head}.json")


def expected_review_request_id(repo: str, pr: int, head: str) -> Optional[str]:
    try:
        with open(_request_marker_path(pr, head), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if (data.get("repo") != repo
            or str(data.get("pr")) != str(pr)
            or data.get("head") != head
            or data.get("request") != "independent_review"
            or not data.get("sent")):
        return None
    request_id = str(data.get("review_request_id") or "").strip()
    return request_id or None


def _exact_body_field(body: str, key: str, expected: str) -> bool:
    values = []
    prefix = key + ":"
    for line in (body or "").splitlines():
        line = line.strip()
        if line.startswith(prefix):
            values.append(line.split(":", 1)[1].strip())
    return len(values) == 1 and values[0] == expected


def _formal_envelope_exact(body: str, repo: str, pr: int, head: str,
                           request_id: Optional[str]) -> bool:
    if not request_id:
        return False
    return (_exact_body_field(body, "REVIEW_REQUEST_ID", request_id)
            and _exact_body_field(body, "REPO", repo)
            and _exact_body_field(body, "PR", str(pr))
            and _exact_body_field(body, "HEAD", head))


def _latest_bound_review(reviews, expected_head: str):
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
    return any(has_formal_review_marker(r.get("body") or "")
               and _author_trusted(r) for r in reviews)


def review_from_github(repo: str, pr: int, expected_head: str,
                       pr_json: Optional[dict] = None,
                       expected_request_id: Optional[str] = None) -> ReviewOutcome:
    """Classify supplied GitHub data.

    When ``expected_request_id`` is supplied (including ``""``), the formal
    COMMENT path is executable only with the exact full active-request
    envelope. Omitting the argument is structural-helper mode for historical
    unit tests; the live ``read_github_pr`` entrypoint never omits it.
    """
    if pr_json is None:
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr,
                             expected_head, [], fail_closed=True)
    head = pr_json.get("headRefOid") or ""
    if not head or head != expected_head:
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr,
                             head or expected_head, [], fail_closed=True)

    rd = pr_json.get("reviewDecision")
    mergeable = pr_json.get("mergeable")
    reviews = pr_json.get("reviews") or []
    enforce_envelope = expected_request_id is not None

    latest = _latest_bound_review(reviews, expected_head)
    if latest is not None:
        body = latest.get("body") or ""
        formal = parse_formal_review_verdict(body)
        if formal.status != "VALID":
            return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                                 [], fail_closed=True)
        if enforce_envelope and not _formal_envelope_exact(
                body, repo, pr, expected_head, expected_request_id):
            return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                                 [], fail_closed=True)
        if formal.verdict == "PASS":
            return ReviewOutcome("COMMENTED", "PASS", repo, pr, head, [body])
        return ReviewOutcome("COMMENTED", formal.verdict, repo, pr, head, [body])

    if _any_trusted_formal(reviews):
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    if rd == "APPROVED" and mergeable in ("MERGEABLE", None):
        if any(r.get("state") == "APPROVED" and _author_trusted(r)
               and _review_binds_head(r, expected_head) for r in reviews):
            return ReviewOutcome("APPROVED", "PASS", repo, pr, head, [])
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    if rd == "CHANGES_REQUESTED":
        findings = []
        bound = False
        for review in reviews:
            if review.get("state") == "CHANGES_REQUESTED" and review.get("body"):
                if _author_trusted(review) and _review_binds_head(review, expected_head):
                    bound = True
                    findings.append(review["body"])
        if bound and findings:
            return ReviewOutcome("CHANGES_REQUESTED", "CHANGES_REQUESTED",
                                 repo, pr, head, findings)
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    if mergeable in ("CONFLICTING", "UNKNOWN"):
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)
    return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                         [], fail_closed=True)


def read_github_pr(repo: str, pr: int, expected_head: str) -> ReviewOutcome:
    """Live executable intake: always enforces the active request envelope."""
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json",
             "reviewDecision,headRefOid,mergeable,state,reviews,updatedAt"],
            capture_output=True, text=True, check=True, timeout=30)
        pr_json = _parse_pr_json(res.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr,
                             expected_head, [], fail_closed=True)
    request_id = expected_review_request_id(repo, pr, expected_head) or ""
    return review_from_github(repo, pr, expected_head, pr_json,
                              expected_request_id=request_id)


def read_pr_head(repo: str, pr: int) -> Optional[str]:
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json", "headRefOid"],
            capture_output=True, text=True, check=True, timeout=30)
        return (json.loads(res.stdout) or {}).get("headRefOid") or None
    except Exception:
        return None
