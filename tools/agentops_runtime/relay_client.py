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

    # P0-3: the retained status_report ACK contract is the exact five-line
    # envelope `REVIEW_REQUEST_ID / REPO / PR / HEAD / ACK`. No aliases. The
    # ACK must bind the SAME REVIEW_REQUEST_ID / REPO / PR / HEAD that was
    # sent and carry the exact `ACK: status_report_received` marker.
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
        got = {}
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("ACK:"):
                got["_ACK"] = line.split("ACK:", 1)[1].strip()
                continue
            for key in sent:
                if line.startswith(key + ":"):
                    got[key] = line.split(":", 1)[1].strip()
        if got.get("_ACK") == "status_report_received" and all(
                sent.get(k) and sent[k] == got.get(k) for k in sent):
            ack = True
            detail = "relay ack captured with exact binding"
    return {"correlation_id": corr, "delivered": ack,
            "exit_code": exit_code, "detail": detail}
