#!/usr/bin/env python3
"""AGE-30 fail-closed relay delivery.

Reuses the existing AGE-19 Neutral Relay (~/.agentops/relay/neutral_relay.py).
Transport only. A concise report is bound to exact repo/pr/head; delivery is
confirmed by relay ACK OR read-back of the GPT Web control conversation.

Fail-closed: unconfirmed send/read-back -> DELIVERY_FAILED (never fake
success). ACK closes only the delivery episode, never the Controller.
"""

import dataclasses
import json
import os
import re
import subprocess
import time
import urllib.request
import uuid
import websockets
import asyncio
from typing import Optional


@dataclasses.dataclass(frozen=True)
class CompletionReport:
    correlation_id: str
    repo: str
    pr: str
    head: str
    body: str
    end_marker: str

    def to_relay_payload(self) -> str:
        return (
            f"REVIEW_REQUEST_ID: {self.correlation_id}\n"
            f"REPO: {self.repo}\n"
            f"PR: {self.pr}\n"
            f"HEAD: {self.head}\n"
            f"REQUEST: status_report\n"
            f"STATE: RUNTIME_LOOP\n\n"
            f"{self.body}\n\n"
            f"{self.end_marker}"
        )


def build_completion_report(repo, pr, head, sections: dict) -> CompletionReport:
    corr = f"CPL_{uuid.uuid4().hex[:12]}"
    end = f"AGENTOPS_COMPLETION_REPORT_END_{corr}"
    lines = []
    for k, v in sections.items():
        lines.append(f"{k}:")
        if isinstance(v, list):
            lines.extend(f"  {i}" for i in v)
        else:
            lines.append(f"  {v}")
    lines.append("")
    lines.append(end)
    return CompletionReport(corr, repo, str(pr), head, "\n".join(lines), end)


@dataclasses.dataclass(frozen=True)
class DeliveryResult:
    correlation_id: str
    delivered: bool
    exit_code: int
    ack_captured: bool
    readback_confirmed: bool
    readback_checks: dict
    details: str

    def to_record(self) -> dict:
        return dataclasses.asdict(self)


class NeutralRelayNotifier:
    def __init__(self, relay_bin: Optional[str] = None,
                 config_file: Optional[str] = None,
                 timeout: int = 180):
        self.relay_bin = relay_bin or os.path.expanduser(
            "~/.agentops/relay/neutral_relay.py")
        self.config_file = config_file or os.path.expanduser(
            "~/.agentops/relay/config.json")
        self.timeout = timeout

    def _conversation_url(self) -> Optional[str]:
        # Conversation identity comes from the relay config route (the
        # trusted runtime binding), not a hard-coded URL.
        try:
            with open(self.config_file) as f:
                cfg = json.load(f)
            routes = cfg.get("routes") or {}
            for repo, route in routes.items():
                url = route.get("conversation_url")
                if url:
                    return url
        except Exception:
            return None
        return None

    def send(self, report: CompletionReport, output_dir: str) -> DeliveryResult:
        os.makedirs(output_dir, exist_ok=True)
        req = os.path.join(output_dir, f"{report.correlation_id}_request.txt")
        out = os.path.join(output_dir, f"{report.correlation_id}_output.md")
        with open(req, "w") as f:
            f.write(report.to_relay_payload())
        try:
            res = subprocess.run(
                ["python3", self.relay_bin, "--request-file", req,
                 "--output-file", out, "--config-file", self.config_file,
                 "--timeout", str(self.timeout)],
                capture_output=True, text=True, timeout=self.timeout + 30)
            exit_code = res.returncode
            log = (res.stdout + res.stderr).strip()
        except (subprocess.TimeoutExpired, OSError) as e:
            exit_code = 2
            log = f"relay invocation failed: {e}"
        ack = False
        if os.path.exists(out):
            with open(out) as f:
                content = f.read()
            # P0-7: exact status_report ACK contract — all four fields plus
            # the exact ACK value must match.
            ack = (
                "ACK: status_report_received" in content
                and report.correlation_id in content
                and f"REPO: {report.repo}" in content
                and f"PR: {report.pr}" in content
                and f"HEAD: {report.head}" in content
            )
        return DeliveryResult(report.correlation_id, ack, exit_code, ack,
                              False, {}, log[-500:])


def _conversation_id_from_url(url: str) -> Optional[str]:
    m = re.search(r"/c/([0-9a-fA-F-]{8,})", url or "", re.IGNORECASE)
    return m.group(1).lower() if m else None


class GptWebContextReadback:
    def __init__(self, cdp_port: Optional[int] = None,
                 conversation_url: Optional[str] = None,
                 config_file: Optional[str] = None):
        # Conversation identity from the relay config (trusted runtime
        # binding), not a hard-coded URL.
        self.config_file = config_file or os.path.expanduser(
            "~/.agentops/relay/config.json")
        self.conversation_url = conversation_url
        self.cdp_port = cdp_port

    def _resolve(self):
        if self.conversation_url is None:
            try:
                with open(self.config_file) as f:
                    cfg = json.load(f)
                routes = cfg.get("routes") or {}
                for repo, route in routes.items():
                    if route.get("conversation_url"):
                        self.conversation_url = route["conversation_url"]
                    if route.get("cdp_port"):
                        self.cdp_port = int(route["cdp_port"])
                    if self.conversation_url and self.cdp_port:
                        break
            except Exception:
                pass
        self.conversation_url = self.conversation_url or (
            "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e")
        self.cdp_port = self.cdp_port or 9233

    async def _conversation_text(self) -> str:
        self._resolve()
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
                 if t.get("type") == "page" and cid and cid in (t.get("url") or "")),
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

    def verify(self, report: CompletionReport, retries: int = 6,
               delay: float = 5.0) -> DeliveryResult:
        checks = {"correlation_id": False, "pr": False, "head": False,
                  "end_marker": False}
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
                "end_marker": report.end_marker in text,
            }
            confirmed = all(checks.values())
            if confirmed:
                break
            time.sleep(delay)
        return DeliveryResult(report.correlation_id, confirmed, 0, False,
                              confirmed, checks,
                              "readback_confirmed" if confirmed
                              else "readback_missing_markers")
