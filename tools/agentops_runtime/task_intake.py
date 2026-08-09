#!/usr/bin/env python3
"""AGE-30 task intake: parse the active Linear issue for mode + criteria.

Reads the REAL Linear issue (via linear_adapter) and extracts:
  - execution mode: AUTO or MANUAL
  - acceptance criteria / scope hints from the description

Rules (CURRENT_RUNTIME_RULES.md):
  - Missing or ambiguous mode -> surface a decision request; do NOT invent
    a default.
  - MANUAL requires a named checkpoint (where the PO decides).
  - No risk classification participates.
"""

import dataclasses
import re
from typing import Optional

from . import linear_adapter


@dataclasses.dataclass(frozen=True)
class TaskSpec:
    identifier: str
    mode: str                 # AUTO | MANUAL
    checkpoint: Optional[str]  # MANUAL only: named PO checkpoint
    acceptance_criteria: list
    description: str
    state_name: str
    state_type: str


def parse_mode(description: str) -> str:
    """Extract AUTO/MANUAL from the description.

    Prefers an explicit `Execution Mode:` field. If absent, accepts a lone
    AUTO or MANUAL marker. If the text contains both without a field, or
    neither, returns "" (caller must surface a decision request).
    """
    if not description:
        return ""
    # Explicit field wins: "Execution Mode: AUTO" OR
    # "## Execution Mode\n\n`AUTO`" (mode on following non-empty line).
    m = re.search(
        r"(?:execution\s*)?mode\s*[:：]\s*(AUTO|MANUAL)", description,
        re.IGNORECASE)
    if not m:
        m = re.search(
            r"##\s*Execution\s+Mode\s*\n+[^A-Za-z]*(AUTO|MANUAL)",
            description, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    has_auto = bool(re.search(r"\bAUTO\b", description, re.IGNORECASE))
    has_manual = bool(re.search(r"\bMANUAL\b", description, re.IGNORECASE))
    if has_auto and not has_manual:
        return "AUTO"
    if has_manual and not has_auto:
        return "MANUAL"
    return ""  # ambiguous / neither


def extract_checkpoint(description: str) -> Optional[str]:
    """Find the MANUAL checkpoint the task names (e.g. 'checkpoint: X')."""
    if not description:
        return None
    for pattern in (
        r"checkpoint\s*[:：]\s*(.+)",
        r"checkpoint\s+(.+)",
        r"PO\s*decision\s*(?:at|on)?\s*[:：]?\s*(.+)",
    ):
        m = re.search(pattern, description, re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def parse_acceptance_criteria(description: str) -> list:
    """Collect acceptance criteria bullets from the description."""
    if not description:
        return []
    out = []
    for line in description.splitlines():
        line = line.strip()
        if line.startswith(("*", "-", "1.", "2.", "3.", "4.", "5.", "6.",
                            "7.", "8.", "9.", "10.")):
            out.append(line.lstrip("* -0123456789.").strip())
    return [c for c in out if c]


def spec_from_linear(identifier: str) -> Optional[TaskSpec]:
    """Build a TaskSpec from the real Linear issue. None if unreadable."""
    issue = linear_adapter.read_linear_issue(identifier)
    if not issue:
        return None
    desc = issue.get("description") or ""
    mode = parse_mode(desc)
    return TaskSpec(
        identifier=identifier,
        mode=mode,
        checkpoint=extract_checkpoint(desc) if mode == "MANUAL" else None,
        acceptance_criteria=parse_acceptance_criteria(desc),
        description=desc,
        state_name=issue.get("state_name") or "",
        state_type=issue.get("state_type") or "",
    )
