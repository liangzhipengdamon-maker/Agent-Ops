#!/usr/bin/env python3
"""Thin task intake: parse the active Linear issue for AUTO/MANUAL + criteria.

Linear provides the task + mode + acceptance criteria. This adapter only
reads Linear (via linear_adapter) and extracts those fields. Missing or
ambiguous mode -> caller surfaces a decision request (no default).
"""

import dataclasses
import re
from typing import Optional

from . import linear_adapter


@dataclasses.dataclass(frozen=True)
class TaskSpec:
    identifier: str
    mode: str
    checkpoint: Optional[str]
    acceptance_criteria: list


def parse_mode(description: str) -> str:
    """Extract AUTO/MANUAL. Prefers an explicit Execution Mode field or
    heading; otherwise a lone AUTO/MANUAL marker. Ambiguous/missing -> ''."""
    if not description:
        return ""
    m = re.search(r"(?:execution\s*)?mode\s*[:：]\s*(AUTO|MANUAL)",
                  description, re.IGNORECASE)
    if not m:
        m = re.search(r"##\s*Execution\s+Mode\s*\n+[^A-Za-z]*(AUTO|MANUAL)",
                      description, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    has_auto = bool(re.search(r"\bAUTO\b", description, re.IGNORECASE))
    has_manual = bool(re.search(r"\bMANUAL\b", description, re.IGNORECASE))
    if has_auto and not has_manual:
        return "AUTO"
    if has_manual and not has_auto:
        return "MANUAL"
    return ""


def extract_checkpoint(description: str) -> Optional[str]:
    if not description:
        return None
    m = re.search(r"checkpoint\s*[:：]\s*(.+)", description, re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None


# Explicit runtime stages a MANUAL checkpoint can name. A checkpoint maps to
# exactly one stage; any other text (including deploy/release/go-live, which
# AGE-30 explicitly excludes) is unevaluable and must fail closed.
_CHECKPOINT_STAGES = {
    "REVIEW_PASS": ("review", "approval", "approve", "sign-off", "signoff",
                    "acceptance", "final approval", "po approval",
                    "po gate", "gate"),
}


def evaluate_checkpoint(checkpoint: Optional[str]) -> Optional[str]:
    """Map a named MANUAL checkpoint to an explicit runtime stage token
    (REVIEW_PASS) or None if unevaluable. R5-P0-2/R6-P0-2: the checkpoint
    text must be matched to a real supported stage; unsupported text (e.g.
    deploy/go-live, which this runtime cannot reach) is not silently treated
    as reached."""
    if not checkpoint:
        return None
    text = checkpoint.strip().lower()
    for stage, keys in _CHECKPOINT_STAGES.items():
        if any(k in text for k in keys):
            return stage
    return None


def parse_acceptance_criteria(description: str) -> list:
    if not description:
        return []
    out = []
    for line in description.splitlines():
        line = line.strip()
        if line.startswith(("*", "-", "1.", "2.", "3.", "4.", "5.",
                            "6.", "7.", "8.", "9.", "10.")):
            out.append(line.lstrip("* -0123456789.").strip())
    return [c for c in out if c]


def spec_from_linear(identifier: str) -> Optional[TaskSpec]:
    issue = linear_adapter.read_linear_issue(identifier)
    if not issue:
        return None
    desc = issue.get("description") or ""
    mode = parse_mode(desc)
    return TaskSpec(identifier=identifier, mode=mode,
                    checkpoint=extract_checkpoint(desc) if mode == "MANUAL"
                    else None,
                    acceptance_criteria=parse_acceptance_criteria(desc))
