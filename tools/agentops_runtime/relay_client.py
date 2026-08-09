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
from typing import Optional

RELAY_BIN = os.path.expanduser("~/.agentops/relay/neutral_relay.py")
CONFIG_FILE = os.path.expanduser("~/.agentops/relay/config.json")


def send_status_report(payload: str, output_dir: str,
                       timeout: int = 180) -> dict:
    """Send a status_report via the existing Neutral Relay.

    `payload` must follow the AGE-18 status_report contract
    (REVIEW_REQUEST_ID / REPO / PR / HEAD / REQUEST / STATE / SUMMARY /
    UNAUTHORIZED_ACTIONS). The relay output file is written on correlated
    capture. Returns a fail-closed result dict.
    """
    os.makedirs(output_dir, exist_ok=True)
    import uuid
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
    ack = False
    if os.path.exists(out):
        with open(out) as f:
            content = f.read()
        ack = "ACK: status_report_received" in content
    return {"correlation_id": corr, "delivered": ack,
            "exit_code": exit_code,
            "detail": "relay ack captured" if ack else "no ack captured"}
