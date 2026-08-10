#!/usr/bin/env python3
"""Thin glue to the existing Neutral Relay (AGE-19).

The Neutral Relay already owns GPT Web transport. This module only shells
out to the existing relay CLI (`~/.agentops/relay/neutral_relay.py`); it
does NOT re-implement CDP/websocket transport or read-back.

Delivery is fail-closed: the relay output file is the only confirmation.
"""

import json
import os
import subprocess
import uuid
from typing import Optional

RELAY_BIN = os.path.expanduser("~/.agentops/relay/neutral_relay.py")
CONFIG_FILE = os.path.expanduser("~/.agentops/relay/config.json")


def _field(payload: str, key: str) -> Optional[str]:
    """Extract `KEY: value` from the status_report payload (first line match)."""
    for line in payload.splitlines():
        if line.startswith(key + ":"):
            val = line.split(":", 1)[1].strip()
            if val:
                return val
    return None


def send_status_report(payload: str, output_dir: str,
                       timeout: int = 180) -> dict:
    """Send a status_report via the existing Neutral Relay.

    `payload` must follow the AGE-18 status_report contract
    (REVIEW_REQUEST_ID / REPO / PR / HEAD / REQUEST / STATE / SUMMARY /
    UNAUTHORIZED_ACTIONS). The relay output file is written on correlated
    capture. Delivery is proven only when the ACK binds the SAME canonical
    REVIEW_REQUEST_ID, REPO, PR, HEAD (no aliases) and carries the exact
    `ACK: status_report_received` marker. Returns a fail-closed result dict.
    """
    os.makedirs(output_dir, exist_ok=True)
    corr = f"CPL_{uuid.uuid4().hex[:12]}"
    req = os.path.join(output_dir, f"{corr}_request.txt")
    out = os.path.join(output_dir, f"{corr}_output.md")
    with open(req, "w") as f:
        f.write(payload)
    try:
        res = subprocess.run(
            ["python3", RELAY_BIN, "--request-file", req,
             "--output-file", out, "--config-file", CONFIG_FILE,
             "--timeout", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 30)
        exit_code = res.returncode
    except (subprocess.TimeoutExpired, OSError) as e:
        exit_code = 2
        detail = f"relay invocation failed: {e}"
        return {"correlation_id": corr, "delivered": False,
                "exit_code": exit_code, "detail": detail}

    # P0-3/R6-P1: the retained status_report ACK contract is the exact
    # five-line envelope `REVIEW_REQUEST_ID / REPO / PR / HEAD / ACK`. No
    # aliases, no extra lines. Parse the output; delivery is confirmed only
    # when the file contains EXACTLY those five lines, the canonical fields
    # match the sent payload, and the ACK is exactly `status_report_received`.
    ack = False
    detail = "no ack captured"
    if os.path.exists(out):
        with open(out) as f:
            content = f.read()
        sent = {
            "REVIEW_REQUEST_ID": _field(payload, "REVIEW_REQUEST_ID"),
            "REPO": _field(payload, "REPO"),
            "PR": _field(payload, "PR"),
            "HEAD": _field(payload, "HEAD"),
        }
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if len(lines) == 5:
            got = {}
            for line in lines:
                key, _, value = line.partition(":")
                got[key.strip()] = value.strip()
            if (list(got.keys()) == ["REVIEW_REQUEST_ID", "REPO", "PR",
                                     "HEAD", "ACK"]
                    and got.get("ACK") == "status_report_received"
                    and all(sent.get(k) and sent[k] == got.get(k)
                            for k in sent)):
                ack = True
                detail = "relay ack captured with exact binding"
    return {"correlation_id": corr, "delivered": ack,
            "exit_code": exit_code, "detail": detail}


def _run_relay(payload: str, output_dir: str, timeout: int) -> dict:
    """Shell out to the existing Neutral Relay with a payload. Returns
    {correlation_id, exit_code, output_file, detail}."""
    os.makedirs(output_dir, exist_ok=True)
    corr = f"CPL_{uuid.uuid4().hex[:12]}"
    req = os.path.join(output_dir, f"{corr}_request.txt")
    out = os.path.join(output_dir, f"{corr}_output.md")
    with open(req, "w") as f:
        f.write(payload)
    try:
        res = subprocess.run(
            ["python3", RELAY_BIN, "--request-file", req,
             "--output-file", out, "--config-file", CONFIG_FILE,
             "--timeout", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 30)
        exit_code = res.returncode
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"correlation_id": corr, "exit_code": 2,
                "output_file": out, "detail": f"relay invocation failed: {e}"}
    return {"correlation_id": corr, "exit_code": exit_code,
            "output_file": out, "detail": "relay invocation returned"}


def _read_output(out: str) -> str:
    try:
        with open(out) as f:
            return f.read()
    except OSError:
        return ""


def send_independent_review(repo: str, pr: str, head: str,
                            output_dir: str, timeout: int = 400) -> dict:
    """Send REQUEST: independent_review via the existing Neutral Relay.

    Thin glue only: builds the exact-bound envelope
    (AUTO_REVIEW_<uuid> / REPO / PR / HEAD / REQUEST: independent_review /
    STATE: FINAL_RESULT_REVIEW) and calls the existing neutral_relay.py.
    Never re-implements CDP/browser transport. Returns
    {correlation_id, sent, exit_code, detail, raw_response}. The response is
    captured from the relay output file (may be empty/incomplete -> caller
    fails closed; the formal verdict also lands on GitHub independently)."""
    req_id = f"AUTO_REVIEW_{uuid.uuid4().hex[:12]}"
    payload = (f"REVIEW_REQUEST_ID: {req_id}\n"
               f"REPO: {repo}\n"
               f"PR: {pr}\n"
               f"HEAD: {head}\n"
               f"REQUEST: independent_review\n"
               f"STATE: FINAL_RESULT_REVIEW\n")
    res = _run_relay(payload, output_dir, timeout)
    return {"correlation_id": res["correlation_id"], "sent": True,
            "review_request_id": req_id,
            "exit_code": res["exit_code"], "detail": res["detail"],
            "output_file": res["output_file"],
            "raw_response": _read_output(res["output_file"])}


def parse_review_response(text: str, repo: str, pr: str, head: str,
                          req_id: str) -> dict:
    """Parse a captured independent_review response.

    Strict (fail closed): the response must contain EXACTLY one
    `AGENTOPS_REVIEW: PASS | CHANGES_REQUESTED | NOT_PASS` verdict AND
    REVIEW_REQUEST_ID / REPO / PR / HEAD each exactly equal to the expected
    values. Missing, duplicate, ambiguous, or mismatched fields -> verdict
    INCOMPLETE (fail closed). Findings after a CHANGES_REQUESTED / NOT_PASS
    verdict are retained verbatim for the Builder.

    Returns {verdict, review_request_id, repo, pr, head, findings, ok}."""
    fields = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("REVIEW_REQUEST_ID:"):
            fields.setdefault("REVIEW_REQUEST_ID", []).append(
                line.split(":", 1)[1].strip())
        elif line.startswith("REPO:"):
            fields.setdefault("REPO", []).append(line.split(":", 1)[1].strip())
        elif line.startswith("PR:"):
            fields.setdefault("PR", []).append(line.split(":", 1)[1].strip())
        elif line.startswith("HEAD:"):
            fields.setdefault("HEAD", []).append(line.split(":", 1)[1].strip())

    def _exactly(key, expected):
        vals = fields.get(key)
        return bool(vals) and len(vals) == 1 and vals[0] == expected

    if not (_exactly("REVIEW_REQUEST_ID", req_id)
            and _exactly("REPO", repo)
            and _exactly("PR", str(pr))
            and _exactly("HEAD", head)):
        return {"verdict": "INCOMPLETE", "review_request_id": req_id,
                "repo": repo, "pr": str(pr), "head": head,
                "findings": [], "ok": False,
                "detail": "exact binding mismatch or duplicate field"}

    verdicts = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("AGENTOPS_REVIEW:"):
            verdicts.append(line.split(":", 1)[1].strip().upper())
    if len(verdicts) != 1 or verdicts[0] not in (
            "PASS", "CHANGES_REQUESTED", "NOT_PASS"):
        return {"verdict": "INCOMPLETE", "review_request_id": req_id,
                "repo": repo, "pr": str(pr), "head": head,
                "findings": [], "ok": False,
                "detail": "missing/duplicate/invalid AGENTOPS_REVIEW verdict"}

    # Findings: everything after the AGENTOPS_REVIEW verdict line, excluding
    # the envelope-binding header lines (they are binding fields, not
    # findings), retained verbatim for the Builder.
    findings = []
    if verdicts[0] in ("CHANGES_REQUESTED", "NOT_PASS"):
        seen = False
        for line in (text or "").splitlines():
            line = line.strip()
            if line.startswith("AGENTOPS_REVIEW:"):
                seen = True
                continue
            if seen and line:
                if line.startswith(("HEAD:", "REVIEW_REQUEST_ID:", "REPO:",
                                    "PR:", "MARKER:")):
                    continue
                findings.append(line)
    return {"verdict": verdicts[0], "review_request_id": req_id,
            "repo": repo, "pr": str(pr), "head": head,
            "findings": findings, "ok": True}


def final_result_auto_review(repo: str, pr: str, head: str,
                             status_payload: str, bridge_dir: str,
                             output_dir: str, timeout: int = 400) -> dict:
    """Final Result Auto-Review trigger.

    Sends the final status_report; then, ONLY IF:
      - status_report delivered=true, AND
      - the status_report STATE is WAITING_REVIEW, AND
      - this repo/pr/head/final-report has NOT already triggered a review
    does it send REQUEST: independent_review and parse the captured verdict.

    WAITING_PO_AUTH never triggers a review even if delivered=true. A failed
    status_report (delivered=false) never triggers a review. Deduped via a
    bridge marker `auto_review_<pr>_<head>.json`.

    Returns {status_delivered, state, review_sent, review, deduped}."""
    status = send_status_report(status_payload, output_dir, timeout)
    state = ""
    for line in (status_payload or "").splitlines():
        if line.startswith("STATE:"):
            state = line.split(":", 1)[1].strip()
    if not status.get("delivered"):
        return {"status_delivered": False, "state": state,
                "review_sent": False, "review": None, "deduped": False,
                "detail": status.get("detail")}
    if state != "WAITING_REVIEW":
        return {"status_delivered": True, "state": state,
                "review_sent": False, "review": None, "deduped": False,
                "detail": f"state {state} does not trigger auto-review"}

    marker = os.path.join(bridge_dir, f"auto_review_{pr}_{head}.json")
    try:
        with open(marker) as f:
            d = json.load(f)
        if d.get("repo") == repo and str(d.get("pr")) == str(pr) \
                and d.get("head") == head and d.get("sent"):
            return {"status_delivered": True, "state": state,
                    "review_sent": False, "review": None, "deduped": True,
                    "detail": "auto-review already sent for this PR+HEAD"}
    except (OSError, json.JSONDecodeError):
        pass

    sent = send_independent_review(repo, pr, head, output_dir, timeout)
    parsed = parse_review_response(
        sent.get("raw_response", ""), repo, pr, head,
        sent.get("review_request_id", ""))
    # P0-1: the success dedupe marker is written ONLY when the relay actually
    # succeeded (exit_code == 0) AND the response parsed ok. A relay failure,
    # empty output, binding mismatch, or INCOMPLETE verdict stays retryable so
    # a later watcher/retry cycle can send the review again.
    succeeded = bool(sent.get("exit_code") == 0 and parsed.get("ok"))
    if succeeded:
        try:
            os.makedirs(bridge_dir, exist_ok=True)
            with open(marker, "w") as f:
                json.dump({"repo": repo, "pr": str(pr), "head": head,
                           "sent": True,
                           "review_request_id": sent.get("review_request_id"),
                           "verdict": parsed.get("verdict")}, f)
        except OSError:
            pass
    return {"status_delivered": True, "state": state,
            "review_sent": True, "review": parsed, "deduped": False,
            "succeeded": succeeded}
