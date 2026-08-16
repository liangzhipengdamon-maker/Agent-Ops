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


# Canonical status_report reply-contract: the 5-line ACK schema the canonical
# send_status_report validator (below) requires is not a ChatGPT-friendly
# contract by default — without an explicit directive, the reviewer is
# happy to also emit STATUS / CHANGED_FILES / ADDITIONS / READY_AUTHORIZED /
# MERGE_AUTHORIZED etc. and break `len(lines) == 5` strict equality.
#
# Appending this block at the end of every status_report payload tells the
# reviewer to reply with EXACTLY the 5 lines, no explanation, no markdown,
# no extra fields, no value mutation. Validator unchanged.
STATUS_REPORT_REPLY_CONTRACT_HEADER = (
    "\n"
    "REPLY_CONTRACT: Your reply MUST contain EXACTLY the 5 lines below,\n"
    "  no explanations, no markdown, no extra fields, no value\n"
    "  mutations, no leading/trailing whitespace beyond what is shown:\n"
)
STATUS_REPORT_REPLY_CONTRACT_FOOTER = (
    "\n"
    "Each value MUST match byte-for-byte.\n"
)


def status_report_reply_contract_block(req_id: str, repo: str,
                                       pr: str, head: str) -> str:
    """Return the REPLY_CONTRACT directive block to append to a status_report
    payload so the canonical reviewer echoes back the 5-line ACK schema
    that ``send_status_report`` validates here. Field values are filled
    in from the live envelope so the reviewer cannot substitute."""
    return (
        STATUS_REPORT_REPLY_CONTRACT_HEADER
        + f"  REVIEW_REQUEST_ID: {req_id}\n"
        + f"  REPO: {repo}\n"
        + f"  PR: {pr}\n"
        + f"  HEAD: {head}\n"
        + "  ACK: status_report_received\n"
        + STATUS_REPORT_REPLY_CONTRACT_FOOTER
    )


# Canonical status_report reply-contract: the 5 fields the canonical
# send_status_report validator (below) requires. The validator now reads
# these five keys anywhere in the assistant turn (extra natural-language
# lines allowed) but enforces byte-exact binding per field and a single
# literal ACK value. Partial-turn safety: a key value that is a strict
# prefix of the request value, an empty value after a key prefix, or a
# last-line key header with no value all fail closed.
ACK_REQUIRED_KEYS = (
    "REVIEW_REQUEST_ID",
    "REPO",
    "PR",
    "HEAD",
    "ACK",
)
ACK_LITERAL_VALUE = "status_report_received"


def _parse_status_ack(content: str, sent_payload: str):
    """Parse the canonical reviewer's status_report ACK reply.

    Returns (ack: bool, detail: str). Failures are ALWAYS fail-closed —
    ``ack`` is True only when all five required keys appear exactly once
    with consistent values, the binding fields match the request
    byte-for-byte, and the ACK value equals the literal marker.

    Partial-turn invariant: a key with no value after its ``KEY:``
    prefix, or a binding value that is a strict prefix of the
    corresponding request value, MUST NOT return ack=True. A truncated
    or ambiguous assistant turn always fails closed.
    """
    if not content or not content.strip():
        return False, "empty assistant turn"

    # Pull the request envelope for byte-exact binding checks.
    sent = {
        "REVIEW_REQUEST_ID": _field(sent_payload, "REVIEW_REQUEST_ID"),
        "REPO": _field(sent_payload, "REPO"),
        "PR": _field(sent_payload, "PR"),
        "HEAD": _field(sent_payload, "HEAD"),
    }

    # Pass 1: collect all occurrences of the five keys.
    occurrences = {key: [] for key in ACK_REQUIRED_KEYS}
    last_non_blank_line = None
    last_non_blank_line_was_partial_header = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        last_non_blank_line = line
        for key in ACK_REQUIRED_KEYS:
            prefix = key + ":"
            if line.startswith(prefix):
                value = line[len(prefix):].strip()
                if value:
                    occurrences[key].append(value)
                    last_non_blank_line_was_partial_header = False
                else:
                    last_non_blank_line_was_partial_header = True
                break
        # Lines that don't start with any required key prefix are natural
        # language and ignored — they do NOT clear the partial-header flag.

    # Pass 2: last-line partial-guard. A ``KEY:`` prefix with no value
    # on the very last non-blank line signals a partial reply (ChatGPT
    # stream truncated mid-field). Run this BEFORE the missing-key check
    # so the more specific "partial" cause is reported rather than a
    # generic "missing required key" symptom.
    if last_non_blank_line_was_partial_header:
        return False, (
            f"last line is partial key header "
            f"(line={last_non_blank_line!r})")

    # Pass 3: every required key must appear exactly once with one value.
    for key in ACK_REQUIRED_KEYS:
        values = occurrences[key]
        if not values:
            return False, f"missing required key {key}"
        if len(values) > 1:
            return False, (
                f"{key} appears {len(values)} times (must appear exactly once); "
                f"values={values!r}")

    # Pass 3: binding fields must equal the request byte-for-byte; a
    # value that is a strict prefix of (or vice versa for) the request
    # value signals a partial/truncated reply and must fail closed.
    for key in ("REVIEW_REQUEST_ID", "REPO", "PR", "HEAD"):
        sent_val = sent[key]
        if not sent_val:
            return False, f"sent payload missing {key}"
        reply_val = occurrences[key][0]
        if reply_val != sent_val:
            if (reply_val and sent_val.startswith(reply_val)) or (
                    reply_val.startswith(sent_val)):
                return False, (
                    f"partial {key} value detected "
                    f"(reply={reply_val!r} sent={sent_val!r})")
            return False, (
                f"{key} binding mismatch "
                f"(reply={reply_val!r} sent={sent_val!r})")

    # Pass 4: ACK literal-match.
    if occurrences["ACK"][0] != ACK_LITERAL_VALUE:
        return False, (
            f"ACK value mismatch "
            f"(reply={occurrences['ACK'][0]!r} expected={ACK_LITERAL_VALUE!r})")

    return True, "relay ack captured with exact binding"


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

    if not os.path.exists(out):
        return {"correlation_id": corr, "delivered": False,
                "exit_code": exit_code,
                "detail": "no relay output file produced"}
    try:
        with open(out) as f:
            content = f.read()
    except OSError as e:
        return {"correlation_id": corr, "delivered": False,
                "exit_code": exit_code,
                "detail": f"failed to read relay output: {e}"}

    ack, detail = _parse_status_ack(content, payload)
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
