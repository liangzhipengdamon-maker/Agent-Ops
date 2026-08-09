#!/usr/bin/env python3
"""AGE-29 canonical risk evaluator (pure).

Implements the AGE-29 risk matrix as a pure decision function with no
side effects. It never grants permission; it only classifies a task into
LOW / MEDIUM / HIGH risk.

Governance boundaries:
- Evidence is not authorization.
- Unknown / ambiguous risk classifies as HIGH (fail closed).
- The evaluator never auto-merges, never auto-deploys, never grants PO
  authorization. It only returns a classification.
"""

import dataclasses
from typing import List, Optional


# ---------------------------------------------------------------------------
# Risk factor definitions (AGE-29 matrix)
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class RiskFactor:
    key: str
    low: bool = False
    medium: bool = False
    high: bool = False


RISK_FACTORS = [
    RiskFactor("production_code"),
    RiskFactor("security_boundary"),
    RiskFactor("authorization_change"),
    RiskFactor("database_schema"),
    RiskFactor("deployment"),
    RiskFactor("merge_action"),
    RiskFactor("protected_path"),
    RiskFactor("irreversible"),
    RiskFactor("scope_deviation"),
    RiskFactor("unknown_impact"),
]

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")

# Factors that ALWAYS imply HIGH (AGE-29 high column triggers)
ALWAYS_HIGH_FACTORS = {
    "authorization_change",
    "deployment",
    "merge_action",
    "protected_path",
    "irreversible",
}

# Factors that at least imply MEDIUM
MEDIUM_MIN_FACTORS = {
    "security_boundary",
    "database_schema",
}


@dataclasses.dataclass(frozen=True)
class RiskDecision:
    level: str  # LOW | MEDIUM | HIGH
    reasons: List[str]
    fail_closed: bool

    def __repr__(self):
        return (f"RiskDecision(level={self.level}, reasons={self.reasons}, "
                f"fail_closed={self.fail_closed})")


def classify_risk(
    production_code: bool = False,
    security_boundary: bool = False,
    authorization_change: bool = False,
    database_schema: bool = False,
    deployment: bool = False,
    merge_action: bool = False,
    protected_path: bool = False,
    irreversible: bool = False,
    scope_deviation: bool = False,
    unknown_impact: bool = False,
    explicit_level: Optional[str] = None,
) -> RiskDecision:
    """Classify a task's risk level per the AGE-29 matrix.

    Max-risk-wins: any HIGH factor => HIGH. Otherwise any MEDIUM factor =>
    MEDIUM. Otherwise LOW.

    Fail closed: if `unknown_impact` is True or `explicit_level` is
    unrecognized, classify HIGH.

    Returns a pure RiskDecision; never grants anything.
    """
    reasons = []
    flagged = {
        "production_code": production_code,
        "security_boundary": security_boundary,
        "authorization_change": authorization_change,
        "database_schema": database_schema,
        "deployment": deployment,
        "merge_action": merge_action,
        "protected_path": protected_path,
        "irreversible": irreversible,
        "scope_deviation": scope_deviation,
        "unknown_impact": unknown_impact,
    }

    # Fail closed on unknown impact.
    if unknown_impact:
        return RiskDecision(level="HIGH", reasons=["unknown_impact"], fail_closed=True)

    # Explicit level override (used by caller for e.g. review verdict).
    if explicit_level is not None:
        if explicit_level not in RISK_LEVELS:
            return RiskDecision(
                level="HIGH", reasons=[f"unrecognized_explicit_level={explicit_level}"],
                fail_closed=True)
        # If the explicit level is HIGH, respect it; if MEDIUM/LOW keep.
        if explicit_level == "HIGH":
            return RiskDecision(level="HIGH", reasons=["explicit_level=HIGH"], fail_closed=False)
        reasons.append(f"explicit_level={explicit_level}")
        level = explicit_level
        for key, val in flagged.items():
            if val and key in ALWAYS_HIGH_FACTORS:
                return RiskDecision(level="HIGH", reasons=[f"{key}=True"], fail_closed=False)
        return RiskDecision(level=level, reasons=reasons, fail_closed=False)

    # Any HIGH factor => HIGH.
    high = [k for k, v in flagged.items() if v and k in ALWAYS_HIGH_FACTORS]
    if high:
        return RiskDecision(level="HIGH", reasons=high, fail_closed=False)

    # Any MEDIUM factor => MEDIUM.
    medium = [k for k, v in flagged.items() if v and k in MEDIUM_MIN_FACTORS]
    if medium:
        reasons.extend(medium)
        return RiskDecision(level="MEDIUM", reasons=reasons, fail_closed=False)

    # Anything else flagged without a HIGH/MEDIUM classifier => conservative MEDIUM.
    flagged_nonlow = [k for k, v in flagged.items() if v]
    if flagged_nonlow:
        reasons.extend(flagged_nonlow)
        return RiskDecision(level="MEDIUM", reasons=reasons, fail_closed=False)

    return RiskDecision(level="LOW", reasons=["no_high_no_medium_factors"], fail_closed=False)
