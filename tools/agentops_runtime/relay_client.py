#!/usr/bin/env python3
"""Thin glue to the existing Neutral Relay (AGE-19).

The Neutral Relay already owns GPT Web transport. This module only shells
out to the existing relay CLI (pre-v0.1 compatibility path shown below); it
does NOT re-implement CDP/websocket transport or read-back.

Delivery is fail-closed: the relay output file is the only confirmation.
"""

import json
import os
import subprocess
import uuid
from typing import Optional

from .review_protocol import (
    REVIEW_MARKERS,
    parse_formal_review_verdict,
)


RELAY_BIN = os.path.expanduser("~/.agentops/relay/neutral_relay.py")
CONFIG_FILE = os.path.expanduser("~/.agentops/relay/config.json")


def _field(payload: str, key: str) -> Optional[str]:
    for line in payload.splitlines():
        if line.startswith(key + ":"):
            val = line.split(":", 1)[1].strip()
            if val:
                return val
    return None


def send_status_report(payload: str, output_dir: str,
                       timeout: int = 180) -> dict:
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
        return {"correlation_id": corr, "delivered": False,
                "exit_code": 2, "detail": f"relay invocation failed: {e}"}

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

    formal = parse_formal_review_verdict(text)
    if formal.status != "VALID":
        return {"verdict": "INCOMPLETE", "review_request_id": req_id,
                "repo": repo, "pr": str(pr), "head": head,
                "findings": [], "ok": False,
                "detail": formal.detail}

    verdict = formal.verdict
    findings = []
    if verdict in ("CHANGES_REQUESTED", "NOT_PASS"):
        seen = False
        for line in (text or "").splitlines():
            line = line.strip()
            if any(line.startswith(marker + ":") for marker in REVIEW_MARKERS):
                seen = True
                continue
            if seen and line:
                if line.startswith(("HEAD:", "REVIEW_REQUEST_ID:", "REPO:",
                                    "PR:", "MARKER:")):
                    continue
                findings.append(line)
    return {"verdict": verdict, "review_request_id": req_id,
            "repo": repo, "pr": str(pr), "head": head,
            "findings": findings, "ok": True,
            "marker": formal.marker}


def _parse_status_payload(payload: str, repo: str, pr: str, head: str) -> dict:
    fields = {}
    for line in (payload or "").splitlines():
        line = line.strip()
        for key in ("REQUEST", "STATE", "REPO", "PR", "HEAD"):
            if line.startswith(key + ":"):
                fields.setdefault(key, []).append(
                    line.split(":", 1)[1].strip())

    def _exact(key, expected):
        vals = fields.get(key)
        return bool(vals) and len(vals) == 1 and vals[0] == expected

    if not (_exact("REQUEST", "status_report")
            and _exact("STATE", "WAITING_REVIEW")):
        return {"ok": False, "state": (fields.get("STATE") or [None])[0],
                "detail": "REQUEST/STATE not exactly status_report/WAITING_REVIEW"}
    if not (_exact("REPO", repo) and _exact("PR", str(pr))
            and _exact("HEAD", head)):
        return {"ok": False, "state": "WAITING_REVIEW",
                "detail": "status payload REPO/PR/HEAD mismatch, duplicate, "
                          "or missing vs invocation arguments"}
    return {"ok": True, "state": "WAITING_REVIEW", "detail": "ok"}


def _persist_review_request(bridge_dir: str, repo: str, pr: str, head: str,
                            request_id: str) -> bool:
    """Persist the exact active request before its verdict can be consumed."""
    if not request_id:
        return False
    try:
        os.makedirs(bridge_dir, exist_ok=True)
        marker = os.path.join(bridge_dir, f"review_request_{pr}_{head}.json")
        tmp = marker + f".{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "repo": repo,
                "pr": str(pr),
                "head": head,
                "request": "independent_review",
                "review_request_id": request_id,
                "sent": True,
            }, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, marker)
        return True
    except OSError:
        return False


def final_result_auto_review(repo: str, pr: str, head: str,
                             status_payload: str, bridge_dir: str,
                             output_dir: str, timeout: int = 400) -> dict:
    status = send_status_report(status_payload, output_dir, timeout)
    binding = _parse_status_payload(status_payload, repo, pr, head)
    if not status.get("delivered"):
        return {"status_delivered": False, "state": binding.get("state"),
                "review_sent": False, "review": None, "deduped": False,
                "binding_ok": binding.get("ok", False),
                "detail": status.get("detail")}
    if not binding.get("ok"):
        return {"status_delivered": True, "state": binding.get("state"),
                "review_sent": False, "review": None, "deduped": False,
                "binding_ok": False, "detail": binding.get("detail")}
    if binding.get("state") != "WAITING_REVIEW":
        return {"status_delivered": True, "state": binding.get("state"),
                "review_sent": False, "review": None, "deduped": False,
                "binding_ok": True,
                "detail": f"state {binding.get('state')} does not trigger "
                          f"auto-review"}

    marker = os.path.join(bridge_dir, f"auto_review_{pr}_{head}.json")
    try:
        with open(marker) as f:
            d = json.load(f)
        if d.get("repo") == repo and str(d.get("pr")) == str(pr) \
                and d.get("head") == head and d.get("sent"):
            return {"status_delivered": True, "state": "WAITING_REVIEW",
                    "review_sent": False, "review": None, "deduped": True,
                    "binding_ok": True,
                    "detail": "auto-review already sent for this PR+HEAD"}
    except (OSError, json.JSONDecodeError):
        pass

    sent = send_independent_review(repo, pr, head, output_dir, timeout)
    request_id = sent.get("review_request_id", "")
    if not _persist_review_request(bridge_dir, repo, pr, head, request_id):
        return {"status_delivered": True, "state": "WAITING_REVIEW",
                "review_sent": bool(sent.get("sent")), "review": None,
                "deduped": False, "succeeded": False, "binding_ok": False,
                "detail": "active independent-review request binding could not be persisted"}

    parsed = parse_review_response(
        sent.get("raw_response", ""), repo, pr, head, request_id)
    succeeded = bool(sent.get("exit_code") == 0 and parsed.get("ok"))
    if succeeded:
        try:
            os.makedirs(bridge_dir, exist_ok=True)
            with open(marker, "w") as f:
                json.dump({"repo": repo, "pr": str(pr), "head": head,
                           "sent": True,
                           "review_request_id": request_id,
                           "verdict": parsed.get("verdict")}, f)
        except OSError:
            pass
    return {"status_delivered": True, "state": "WAITING_REVIEW",
            "review_sent": True, "review": parsed, "deduped": False,
            "succeeded": succeeded, "binding_ok": True}
