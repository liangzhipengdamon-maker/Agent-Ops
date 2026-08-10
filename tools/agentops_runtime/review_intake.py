#!/usr/bin/env python3
"""AGE-30 review intake: real GitHub PR review bound to exact request+PR+HEAD.

Formal GovernLoop COMMENT reviews are executable only when all of these hold:
- trusted reviewer identity;
- exactly one canonical/legacy formal verdict marker;
- exact current HEAD;
- exact active REVIEW_REQUEST_ID / REPO / PR / HEAD envelope.

The active review request is written by the relay/controller before the
independent-review delivery attempt. Missing or mismatched request state fails
closed; GitHub review text cannot self-select which request it answers.
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
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    for base in (pathlib.Path.cwd(), here, here.parent, here.parent.parent,
                 here.parent.parent.parent):
        p = base / "profiles" / "agentops.json"
        if p.exists():
            return str(p)
    return None


def trusted_reviewers() -> set:
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
    login = ((r.get("author") or {}).get("login") or "").strip()
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


def _review_binds_head(r: dict, expected_head: str) -> bool:
    commit = (r.get("commit_id") or "").lower()
    if not commit:
        commit = ((r.get("commit") or {}).get("oid") or "").lower()
    if commit and commit == expected_head.lower():
        return True
    m = re.search(r"^HEAD:\s*(\S+)\s*$", r.get("body") or "", re.MULTILINE)
    return bool(m) and m.group(1).strip().lower() == expected_head.lower()


def _bridge_dir() -> str:
    return os.environ.get("AGENT_BRIDGE_DIR", ".agent-bridge")


def _request_marker_path(pr: int, head: str) -> str:
    return os.path.join(_bridge_dir(), f"review_request_{pr}_{head}.json")


def expected_review_request_id(repo: str, pr: int, head: str) -> Optional[str]:
    """Read the active controller-issued request binding for this PR+HEAD."""
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
    req = str(data.get("review_request_id") or "").strip()
    return req or None


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
    """Formal COMMENT review must answer one exact active request."""
    if not request_id:
        return False
    return (
        _exact_body_field(body, "REVIEW_REQUEST_ID", request_id)
        and _exact_body_field(body, "REPO", repo)
        and _exact_body_field(body, "PR", str(pr))
        and _exact_body_field(body, "HEAD", head)
    )


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

    if expected_request_id is None:
        expected_request_id = expected_review_request_id(repo, pr, expected_head)

    latest = _latest_bound_review(reviews, expected_head)
    if latest is not None:
        body = latest.get("body") or ""
        formal = parse_formal_review_verdict(body)
        if (formal.status != "VALID"
                or not _formal_envelope_exact(
                    body, repo, pr, expected_head, expected_request_id)):
            return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                                 [], fail_closed=True)
        verdict = formal.verdict
        if verdict == "PASS":
            return ReviewOutcome("COMMENTED", "PASS", repo, pr, head, [body])
        return ReviewOutcome("COMMENTED", verdict, repo, pr, head, [body])

    if _any_trusted_formal(reviews):
        return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                             [], fail_closed=True)

    # Native GitHub reviews are independently anchored by GitHub's submitted
    # review object + commit oid; the GovernLoop request envelope applies to
    # the formal machine-readable COMMENT path above.
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

    return ReviewOutcome("INCOMPLETE", "INCOMPLETE", repo, pr, head,
                         [], fail_closed=True)


def read_github_pr(repo: str, pr: int, expected_head: str) -> ReviewOutcome:
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
    return review_from_github(
        repo, pr, expected_head, pr_json,
        expected_request_id=expected_review_request_id(repo, pr, expected_head))


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
