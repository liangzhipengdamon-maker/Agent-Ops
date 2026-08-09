#!/usr/bin/env python3
"""AGE-24 / AGE-29 transition controller (risk -> routing + state writeback).

Combines a risk decision (AGE-29) and a review decision (AGE-28) into a
routing outcome:

  - HIGH risk                 -> WAITING_PO_AUTH (PO final; never auto-merge)
  - MEDIUM risk               -> GPT_DECISION_REQUIRED (must ask GPT Web)
  - LOW risk + PASS review    -> AUTO_CONTINUE
  - LOW risk + CHANGES_REQUESTED -> FOLLOW_UP_REQUIRED
  - LOW risk + INCOMPLETE     -> WAIT_REVIEW (incomplete evidence)

AGE-30 hardening — mandatory PO notification before WAITING_PO_AUTH:
  When the controller decides the task must enter WAITING_PO_AUTH, it
  MUST first generate a PO status report, send it to GPT Web via the
  existing Neutral Relay (AGE-19), and capture the delivery result BEFORE
  recording the WAITING_PO_AUTH state.

Governance boundaries:
- The controller NEVER grants merge/deploy permission.
- PO authorization is never bypassed for HIGH risk.
- Review evidence is not authorization.
- Risk Policy (AGE-29) is unchanged.
- PO Authorization rules are unchanged.
- The notify step does NOT auto-execute any PO decision.
"""

import dataclasses
import json
import os
import subprocess
import time
import uuid
from typing import List, Optional


@dataclasses.dataclass(frozen=True)
class TransitionOutcome:
    route: str  # WAITING_PO_AUTH | GPT_DECISION_REQUIRED | AUTO_CONTINUE | FOLLOW_UP_REQUIRED | WAIT_REVIEW
    risk: str
    review: str
    reason: str

    def to_record(self) -> dict:
        return {
            "route": self.route,
            "risk": self.risk,
            "review": self.review,
            "reason": self.reason,
        }


def route_decision(risk_level: str, review_decision: str) -> TransitionOutcome:
    """Pure routing function (no side effects)."""
    if risk_level == "HIGH":
        return TransitionOutcome(
            route="WAITING_PO_AUTH", risk=risk_level, review=review_decision,
            reason="high_risk_requires_po_authorization")
    if risk_level == "MEDIUM":
        return TransitionOutcome(
            route="GPT_DECISION_REQUIRED", risk=risk_level, review=review_decision,
            reason="medium_risk_requires_gpt_web_judgment")
    # LOW risk path
    if review_decision == "PASS":
        return TransitionOutcome(
            route="AUTO_CONTINUE", risk=risk_level, review=review_decision,
            reason="low_risk_and_review_pass")
    if review_decision == "CHANGES_REQUESTED":
        return TransitionOutcome(
            route="FOLLOW_UP_REQUIRED", risk=risk_level, review=review_decision,
            reason="review_changes_requested")
    # INCOMPLETE / BLOCKED / COMMENTED
    return TransitionOutcome(
        route="WAIT_REVIEW", risk=risk_level, review=review_decision,
        reason=f"incomplete_review_evidence_{review_decision}")


def write_state(outcome: TransitionOutcome, task_state_path: str) -> str:
    """Append the transition outcome to the durable task-state file.

    Returns the path written. Fail-open only for the local record; the
    caller must not treat a write failure as a permission grant.
    """
    os.makedirs(os.path.dirname(task_state_path) or ".", exist_ok=True)
    state = {"outcome": outcome.to_record(), "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with open(task_state_path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    return task_state_path


# ---------------------------------------------------------------------------
# Mandatory PO notification before WAITING_PO_AUTH (AGE-30 hardening)
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class PoStatusReport:
    """AGE-31/33 PO status report event model."""
    event_id: str
    correlation_id: str
    task_id: str
    repo: str
    pr: str
    head: str
    state: str
    summary: str
    delivery_targets: List[str]

    def to_relay_payload(self) -> str:
        """AGE-18 status_report contract payload."""
        return (
            f"REVIEW_REQUEST_ID: {self.correlation_id}\n"
            f"REPO: {self.repo}\n"
            f"PR: {self.pr}\n"
            f"HEAD: {self.head}\n"
            f"REQUEST: status_report\n"
            f"STATE: {self.state}\n"
            f"SUMMARY: {self.summary}\n"
            f"UNAUTHORIZED_ACTIONS: NONE\n"
        )


@dataclasses.dataclass(frozen=True)
class DeliveryResult:
    """Result of delivering the PO status report via Neutral Relay."""
    correlation_id: str
    delivered: bool          # relay exit 0 AND ACK captured
    exit_code: int
    ack_captured: bool
    details: str

    def to_record(self) -> dict:
        return {
            "correlation_id": self.correlation_id,
            "delivered": self.delivered,
            "exit_code": self.exit_code,
            "ack_captured": self.ack_captured,
            "details": self.details,
        }


def build_po_status_report(
    task_id: str, repo: str, pr: str, head: str, summary: str,
    state: str = "WAITING_PO_AUTH",
) -> PoStatusReport:
    """Generate the PO status report (AGE-31 event model)."""
    return PoStatusReport(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        correlation_id=f"PO_{uuid.uuid4().hex[:12]}",
        task_id=task_id,
        repo=repo,
        pr=str(pr),
        head=head,
        state=state,
        summary=summary,
        delivery_targets=["gpt_web", "po_channel"],
    )


class NeutralRelayNotifier:
    """Sends a PO status report via the existing Neutral Relay (AGE-19).

    Reuses `~/.agentops/relay/neutral_relay.py` (the AGE-19 hardened relay).
    It is transport-only: it does not judge the report and does not make
    any PO decision.
    """

    def __init__(self, relay_bin: Optional[str] = None,
                 config_file: Optional[str] = None,
                 timeout: int = 180):
        self.relay_bin = relay_bin or os.path.expanduser(
            "~/.agentops/relay/neutral_relay.py")
        self.config_file = config_file or os.path.expanduser(
            "~/.agentops/relay/config.json")
        self.timeout = timeout

    def send(self, report: PoStatusReport, output_dir: str) -> DeliveryResult:
        os.makedirs(output_dir, exist_ok=True)
        req_path = os.path.join(output_dir, f"{report.correlation_id}_request.txt")
        out_path = os.path.join(output_dir, f"{report.correlation_id}_output.md")
        with open(req_path, "w") as f:
            f.write(report.to_relay_payload())

        try:
            res = subprocess.run(
                ["python3", self.relay_bin,
                 "--request-file", req_path,
                 "--output-file", out_path,
                 "--config-file", self.config_file,
                 "--timeout", str(self.timeout)],
                capture_output=True, text=True, timeout=self.timeout + 30,
            )
            exit_code = res.returncode
            log = (res.stdout + res.stderr).strip()
        except (subprocess.TimeoutExpired, OSError) as e:
            exit_code = 2
            log = f"relay invocation failed: {e}"

        ack_captured = False
        if os.path.exists(out_path):
            with open(out_path) as f:
                content = f.read()
            ack_captured = (
                "ACK:" in content
                and report.correlation_id in content
                and report.head in content
            )

        delivered = exit_code == 0 and ack_captured
        return DeliveryResult(
            correlation_id=report.correlation_id,
            delivered=delivered,
            exit_code=exit_code,
            ack_captured=ack_captured,
            details=log[-500:],
        )


def transition_with_po_notify(
    risk_level: str,
    review_decision: str,
    task_id: str,
    repo: str,
    pr: str,
    head: str,
    summary: str,
    output_dir: str,
    notifier: Optional[NeutralRelayNotifier] = None,
    task_state_path: Optional[str] = None,
) -> dict:
    """Orchestrate routing + mandatory PO notify + state writeback.

    Steps:
      1. route_decision(risk, review)
      2. If route == WAITING_PO_AUTH:
           a. generate PO status report
           b. send via Neutral Relay
           c. capture delivery result
      3. Write state (if task_state_path given)

    Returns a dict with the outcome and delivery result.
    """
    outcome = route_decision(risk_level, review_decision)
    notifier = notifier or NeutralRelayNotifier()
    delivery = None

    if outcome.route == "WAITING_PO_AUTH":
        report = build_po_status_report(
            task_id=task_id, repo=repo, pr=pr, head=head, summary=summary,
            state="WAITING_PO_AUTH",
        )
        delivery = notifier.send(report, output_dir)

    if task_state_path:
        write_state(outcome, task_state_path)

    result = {"outcome": outcome.to_record()}
    if delivery is not None:
        result["po_notify"] = delivery.to_record()
    return result
