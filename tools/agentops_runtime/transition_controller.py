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
  Before recording WAITING_PO_AUTH the controller MUST, in order:
    1. have the full detailed report committed to GitHub (authoritative
       detailed record; caller performs the commit, controller receives
       the committed path + URL),
    2. build a CONCISE completion report (not the full report body),
    3. send it to GPT Web via the existing Neutral Relay (AGE-19),
    4. read-back verify the concise report reached the GPT Web control
       conversation (correlation_id, PR, HEAD, GitHub path, end marker),
    5. only then write the WAITING_PO_AUTH state.

  If delivery/read-back is not confirmed, record DELIVERY_FAILED (never
  fake success) and still stop safely without any PO follow-up action.

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
import urllib.request
import uuid
import websockets
import asyncio
import re
from typing import List, Optional


# ---------------------------------------------------------------------------
# Pure routing + state writeback
# ---------------------------------------------------------------------------

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
class CompletionReport:
    """A CONCISE completion report sent to GPT Web / PO.

    Deliberately NOT the full detailed report: the full report lives on
    GitHub (deliverable_path / deliverable_url) and is only referenced by
    link. The concise report carries the required sections so the PO can
    act without manual forwarding.
    """
    correlation_id: str
    repo: str
    pr: str
    head: str
    deliverable_path: str      # repo-relative path (e.g. docs/plans/...)
    deliverable_url: str       # full GitHub URL
    body: str                  # concise multi-section report
    end_marker: str            # unique completion-report end marker

    def to_relay_payload(self) -> str:
        return (
            f"REVIEW_REQUEST_ID: {self.correlation_id}\n"
            f"REPO: {self.repo}\n"
            f"PR: {self.pr}\n"
            f"HEAD: {self.head}\n"
            f"REQUEST: completion_report\n"
            f"STATE: WAITING_PO_AUTH\n"
            f"DELIVERABLE_PATH: {self.deliverable_path}\n"
            f"DELIVERABLE_URL: {self.deliverable_url}\n"
            f"END_MARKER: {self.end_marker}\n\n"
            f"{self.body}"
        )


def build_completion_report(
    task_id: str,
    repo: str,
    pr: str,
    head: str,
    deliverable_path: str,
    deliverable_url: str,
    sections: dict,
) -> CompletionReport:
    """Build a CONCISE completion report from named sections.

    `sections` is an ordered dict of {title: content_lines_or_str}.
    The report body is a plain-text, terminal-style summary.
    """
    correlation_id = f"CPL_{uuid.uuid4().hex[:12]}"
    end_marker = f"AGENTOPS_COMPLETION_REPORT_END_{correlation_id}"
    lines = [f"Task: {task_id}"]
    for title, content in sections.items():
        lines.append("")
        lines.append(f"{title}:")
        if isinstance(content, list):
            lines.extend(f"  {c}" for c in content)
        else:
            lines.append(f"  {content}")
    lines.append("")
    lines.append(end_marker)
    return CompletionReport(
        correlation_id=correlation_id,
        repo=repo,
        pr=str(pr),
        head=head,
        deliverable_path=deliverable_path,
        deliverable_url=deliverable_url,
        body="\n".join(lines),
        end_marker=end_marker,
    )


@dataclasses.dataclass(frozen=True)
class DeliveryResult:
    """Result of delivering the concise completion report via Neutral Relay."""
    correlation_id: str
    delivered: bool          # relay exit 0 AND (ack_captured OR readback_confirmed)
    exit_code: int
    ack_captured: bool
    readback_confirmed: bool
    readback_checks: dict
    details: str

    def to_record(self) -> dict:
        return {
            "correlation_id": self.correlation_id,
            "delivered": self.delivered,
            "exit_code": self.exit_code,
            "ack_captured": self.ack_captured,
            "readback_confirmed": self.readback_confirmed,
            "readback_checks": self.readback_checks,
            "details": self.details,
        }


class NeutralRelayNotifier:
    """Sends a completion report via the existing Neutral Relay (AGE-19).

    Reuses `~/.agentops/relay/neutral_relay.py` (the AGE-19 hardened relay).
    Transport-only: it does not judge the report and does not make any PO
    decision.
    """

    def __init__(self, relay_bin: Optional[str] = None,
                 config_file: Optional[str] = None,
                 timeout: int = 180):
        self.relay_bin = relay_bin or os.path.expanduser(
            "~/.agentops/relay/neutral_relay.py")
        self.config_file = config_file or os.path.expanduser(
            "~/.agentops/relay/config.json")
        self.timeout = timeout

    def send(self, report: CompletionReport, output_dir: str) -> DeliveryResult:
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

        return DeliveryResult(
            correlation_id=report.correlation_id,
            delivered=ack_captured,  # provisional; read-back may upgrade
            exit_code=exit_code,
            ack_captured=ack_captured,
            readback_confirmed=False,
            readback_checks={},
            details=log[-500:],
        )


def _conversation_id_from_url(url: str) -> Optional[str]:
    m = re.search(r"/c/([0-9a-fA-F-]{8,})", url or "", re.IGNORECASE)
    return m.group(1).lower() if m else None


def query_live_pr_head(repo: str, pr: str) -> Optional[str]:
    """Query the CURRENT live PR HEAD via `gh` (authoritative).

    Returns the exact headRefOid, or None on any failure (fail closed).
    """
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json", "headRefOid"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        data = json.loads(res.stdout)
        head = (data.get("headRefOid") or "").strip()
        return head if head else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            OSError, json.JSONDecodeError):
        return None


class GptWebContextReadback:
    """Reads back the GPT Web control conversation to verify delivery.

    Uses the SAME CDP mechanism as the Neutral Relay (AGE-19) on the
    isolated AgentOps runtime. It reads the conversation text and checks
    the concise report's correlation_id, PR, HEAD, GitHub deliverable
    path, and end marker are present.
    """

    def __init__(self, cdp_port: int = 9233, conversation_url: Optional[str] = None):
        self.cdp_port = cdp_port
        self.conversation_url = conversation_url or (
            "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e")

    async def _conversation_text(self) -> str:
        cid = _conversation_id_from_url(self.conversation_url)
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=8) as r:
            ws_url = json.loads(r.read().decode()).get("webSocketDebuggerUrl", "")
        async with websockets.connect(ws_url, max_size=2**30, open_timeout=10) as ws:
            _id = 0

            async def cmd(method, params=None, session=None):
                nonlocal _id
                _id += 1
                mid = _id
                msg = {"id": mid, "method": method}
                if params is not None:
                    msg["params"] = params
                if session:
                    msg["sessionId"] = session
                await ws.send(json.dumps(msg))
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                    data = json.loads(raw)
                    if data.get("id") == mid:
                        return data

            r = await cmd("Target.getTargets")
            target = next(
                (t for t in r.get("result", {}).get("targetInfos", [])
                 if t.get("type") == "page"
                 and cid and cid in (t.get("url") or "")),
                None)
            if not target:
                return ""
            at = await cmd("Target.attachToTarget",
                           {"targetId": target["targetId"], "flatten": True})
            sid = at.get("result", {}).get("sessionId")
            ev = await cmd("Runtime.evaluate", {
                "expression": "document.body ? document.body.innerText.slice(0, 60000) : ''",
                "returnByValue": True, "awaitPromise": True,
            }, session=sid)
            return str(ev.get("result", {}).get("result", {}).get("value", ""))

    def verify(self, report: CompletionReport, retries: int = 6, delay: float = 5.0) -> DeliveryResult:
        """Read back and verify the concise report reached the conversation."""
        checks = {
            "correlation_id": False,
            "pr": False,
            "head": False,
            "deliverable_path": False,
            "end_marker": False,
        }
        confirmed = False
        text = ""
        for _ in range(retries):
            try:
                text = asyncio.run(self._conversation_text())
            except Exception:
                text = ""
            checks = {
                "correlation_id": report.correlation_id in text,
                "pr": f"PR: {report.pr}" in text,
                "head": f"HEAD: {report.head}" in text,
                "deliverable_path": report.deliverable_path in text,
                "end_marker": report.end_marker in text,
            }
            confirmed = all(checks.values())
            if confirmed:
                break
            time.sleep(delay)
        return DeliveryResult(
            correlation_id=report.correlation_id,
            delivered=confirmed,
            exit_code=0,
            ack_captured=False,
            readback_confirmed=confirmed,
            readback_checks=checks,
            details="readback_confirmed" if confirmed else "readback_missing_markers",
        )


def transition_with_po_notify(
    risk_level: str,
    review_decision: str,
    task_id: str,
    repo: str,
    pr: str,
    head: str,
    deliverable_path: str,
    deliverable_url: str,
    completion_sections: dict,
    output_dir: str,
    notifier: Optional[NeutralRelayNotifier] = None,
    readback: Optional[GptWebContextReadback] = None,
    task_state_path: Optional[str] = None,
) -> dict:
    """Orchestrate routing + mandatory completion-report delivery + read-back.

    Steps (only for WAITING_PO_AUTH):
      1. build CONCISE completion report (full report already committed to
         GitHub by caller; deliverable_path/url reference it)
      2. send via Neutral Relay
      3. read-back verify (correlation_id, PR, HEAD, deliverable path,
         end marker)
      4. if relay ACK captured OR read-back confirms -> delivered; else
         record DELIVERY_FAILED (never fake success)
      5. write WAITING_PO_AUTH state (with delivery record)

    For non-WAITING_PO_AUTH routes, no notify happens; state may still be
    written.
    """
    outcome = route_decision(risk_level, review_decision)
    notifier = notifier or NeutralRelayNotifier()
    readback = readback or GptWebContextReadback()
    delivery = None

    if outcome.route == "WAITING_PO_AUTH":
        report = build_completion_report(
            task_id=task_id, repo=repo, pr=pr, head=head,
            deliverable_path=deliverable_path, deliverable_url=deliverable_url,
            sections=completion_sections,
        )
        # 2. send via Neutral Relay
        relay_delivery = notifier.send(report, output_dir)
        # 3. read-back verify
        rb = readback.verify(report)

        # 4. delivered only if ack captured OR read-back confirmed
        delivered = relay_delivery.ack_captured or rb.readback_confirmed
        delivery = DeliveryResult(
            correlation_id=report.correlation_id,
            delivered=delivered,
            exit_code=relay_delivery.exit_code,
            ack_captured=relay_delivery.ack_captured,
            readback_confirmed=rb.readback_confirmed,
            readback_checks=rb.readback_checks,
            details=(
                "delivered" if delivered
                else "DELIVERY_FAILED: no ack and read-back did not confirm"
            ),
        )

    # FAIL-CLOSED DELIVERY: write WAITING_PO_AUTH only when the notification
    # was confirmed delivered. If delivery failed, record DELIVERY_FAILED and
    # do NOT claim the task safely entered WAITING_PO_AUTH.
    if task_state_path:
        if outcome.route == "WAITING_PO_AUTH":
            if delivery is not None and not delivery.delivered:
                write_state(
                    TransitionOutcome(
                        route="DELIVERY_FAILED",
                        risk=risk_level,
                        review=review_decision,
                        reason="po_notification_not_confirmed",
                    ),
                    task_state_path,
                )
            else:
                write_state(outcome, task_state_path)
        else:
            write_state(outcome, task_state_path)

    result = {"outcome": outcome.to_record()}
    if delivery is not None:
        result["po_notify"] = delivery.to_record()
        if delivery.delivered:
            result["po_notify"]["status"] = "DELIVERED"
        else:
            result["po_notify"]["status"] = "DELIVERY_FAILED"
            # reflect fail-closed in the reported outcome route as well
            result["outcome"]["route"] = "DELIVERY_FAILED"
    return result
