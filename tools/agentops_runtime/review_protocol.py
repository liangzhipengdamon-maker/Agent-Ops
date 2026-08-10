#!/usr/bin/env python3
"""Canonical GovernLoop independent-review response protocol.

GovernLoop v0.1 uses ``GOVERNLOOP_REVIEW`` as the public executable verdict
marker. ``AGENTOPS_REVIEW`` is accepted only as a pre-v0.1 compatibility
marker. The parser is intentionally strict: one response/review body must
contain exactly one recognized marker line with one valid verdict. Duplicate
or mixed canonical/legacy marker lines are ambiguous and fail closed.
"""

from dataclasses import dataclass
from typing import Optional


CANONICAL_REVIEW_MARKER = "GOVERNLOOP_REVIEW"
LEGACY_REVIEW_MARKER = "AGENTOPS_REVIEW"
REVIEW_MARKERS = (CANONICAL_REVIEW_MARKER, LEGACY_REVIEW_MARKER)
VALID_REVIEW_VERDICTS = ("PASS", "CHANGES_REQUESTED", "NOT_PASS")


@dataclass(frozen=True)
class FormalReviewVerdict:
    status: str  # NONE | VALID | INVALID
    marker: Optional[str] = None
    verdict: Optional[str] = None
    detail: str = ""


def _marker_line(line: str):
    stripped = (line or "").strip()
    for marker in REVIEW_MARKERS:
        prefix = marker + ":"
        if stripped.startswith(prefix):
            return marker, stripped.split(":", 1)[1].strip().upper()
    return None


def has_formal_review_marker(text: str) -> bool:
    """Return True when any canonical or legacy formal marker line exists."""
    return any(_marker_line(line) is not None for line in (text or "").splitlines())


def parse_formal_review_verdict(text: str) -> FormalReviewVerdict:
    """Parse exactly one canonical/legacy formal review verdict line.

    Canonical and legacy markers are protocol aliases during the migration,
    not two independent verdict channels. Therefore a body containing two
    marker lines -- even when both say PASS -- is ambiguous and INVALID.
    """
    matches = []
    for line in (text or "").splitlines():
        parsed = _marker_line(line)
        if parsed is not None:
            matches.append(parsed)

    if not matches:
        return FormalReviewVerdict("NONE", detail="no formal review marker")
    if len(matches) != 1:
        return FormalReviewVerdict(
            "INVALID",
            detail="duplicate or mixed canonical/legacy review markers",
        )

    marker, verdict = matches[0]
    if verdict not in VALID_REVIEW_VERDICTS:
        return FormalReviewVerdict(
            "INVALID", marker=marker, verdict=verdict,
            detail="invalid formal review verdict",
        )
    return FormalReviewVerdict(
        "VALID", marker=marker, verdict=verdict, detail="ok")
