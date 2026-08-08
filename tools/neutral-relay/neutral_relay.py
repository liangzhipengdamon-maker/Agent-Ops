#!/usr/bin/env python3
"""Neutral Relay Transport for Agent-Ops (hardened).

Transport-only relay between the local Builder and the external ChatGPT
Reviewer conversation, via Chrome DevTools Protocol (CDP).

Boundaries (unchanged):
- Relay ONLY transports: request in -> response out.
- Relay never judges PASS / CHANGES_REQUESTED / authorization.
- Relay never performs Ready / Merge / Deploy / workflow-state transitions.

Hardening (AGE-19):
- Strict Conversation Identity Binding: the relay targets exactly ONE
  configured reviewer conversation (exact normalized URL match). It never
  picks the first ChatGPT tab, the most recently active tab, a generic title,
  or any historical conversation. Zero matches -> REVIEWER_CONVERSATION_NOT_FOUND;
  more than one exact match -> AMBIGUOUS_REVIEWER_CONVERSATION. Identity is
  re-verified after attach and before/after every send; on any drift the
  relay fails closed and does not send.
- Robust, non-brittle composer + send-control detection with a bounded
  fallback selector chain (semantic / accessibility attributes + visibility).
- Explicit send state machine with bounded timeouts and fail-closed errors.
- Reconcile-before-resend: after a send click, read back the conversation to
  determine whether the request actually appeared. Never blind-retry.
- Duplicate-send protection: if the request_id already appears in the
  conversation (e.g. a previous relay invocation already sent it), do not send
  again; wait for the correlated response instead. This makes the outer
  relay_adapter retry loop idempotent.
- Strict correlation: a captured response must bind request_id, repo, PR and
  HEAD. Stale / previous-request / mismatched responses are rejected.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.request

import websockets

# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

REQUIRED_ENVELOPE_FIELDS = ("REPO", "REVIEW_REQUEST_ID", "PR", "HEAD", "REQUEST")


def parse_envelope(request_text):
    """Extract the routing/correlation fields from the request payload.

    Returns a dict mapping each REQUIRED_ENVELOPE_FIELDS key to its value.
    Missing or empty fields remain None so the caller can fail closed.
    """
    envelope = {}
    for line in (request_text or "").splitlines():
        for key in REQUIRED_ENVELOPE_FIELDS:
            if line.startswith(f"{key}:"):
                val = line.split(f"{key}:", 1)[1].strip()
                if val:
                    envelope[key] = val
    return {k: envelope.get(k) for k in REQUIRED_ENVELOPE_FIELDS}


# ---------------------------------------------------------------------------
# Conversation Identity Binding
# ---------------------------------------------------------------------------

class ConversationIdentityError(Exception):
    """Fail-closed identity resolution error (REVIEWER_CONVERSATION_*)."""

    def __init__(self, code, reason):
        super().__init__(f"[{code}] {reason}")
        self.code = code
        self.reason = reason


def conversation_id_from_url(url):
    """Extract the exact conversation UUID from a ChatGPT /c/<id> URL.

    Returns the normalized UUID string (lowercase) or None if the URL does
    not identify a specific ChatGPT conversation.
    """
    if not url:
        return None
    m = re.search(r"/c/([0-9a-fA-F-]{8,})", url, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower()


def normalize_conversation_url(url):
    """Normalize a reviewer conversation URL to a canonical identity.

    Returns the exact /c/<uuid> canonical form, or None for URLs that do not
    identify a specific conversation (homepage, generic, /g/, /share/, etc.).
    """
    cid = conversation_id_from_url(url)
    if not cid:
        return None
    return f"https://chatgpt.com/c/{cid}"


def target_matches_reviewer(target_url, reviewer_url):
    """Exact conversation identity match (UUID equality), never substring."""
    reviewer_cid = conversation_id_from_url(reviewer_url)
    if not reviewer_cid:
        return False
    return conversation_id_from_url(target_url) == reviewer_cid


def resolve_reviewer_target(targets, reviewer_url):
    """Select exactly one reviewer conversation among CDP page targets.

    Returns the single matching target dict.
    Raises ConversationIdentityError:
      - REVIEWER_CONVERSATION_NOT_FOUND if zero targets match.
      - AMBIGUOUS_REVIEWER_CONVERSATION if more than one target matches.
    """
    reviewer_cid = conversation_id_from_url(reviewer_url)
    if not reviewer_cid:
        raise ConversationIdentityError(
            "INVALID_REVIEWER_CONVERSATION_URL",
            f"configured reviewer URL does not identify a conversation: {reviewer_url!r}")
    matches = [
        t for t in targets
        if t.get("type") == "page"
        and conversation_id_from_url(t.get("url") or "") == reviewer_cid
    ]
    if len(matches) == 0:
        raise ConversationIdentityError(
            "REVIEWER_CONVERSATION_NOT_FOUND",
            f"no open tab matches configured reviewer conversation {reviewer_cid!r}")
    if len(matches) > 1:
        raise ConversationIdentityError(
            "AMBIGUOUS_REVIEWER_CONVERSATION",
            f"{len(matches)} tabs match reviewer conversation {reviewer_cid!r}; refusing to guess")
    return matches[0]


# ---------------------------------------------------------------------------
# Pure decision / correlation helpers (unit-testable, no CDP)
# ---------------------------------------------------------------------------

def normalize_text(s):
    """Whitespace-normalized text used for content comparison."""
    if not s:
        return ""
    return "".join(str(s).split())


def extract_latest_assistant_response(assistant_messages, req_id):
    """Compatibility shim (kept for existing tests).

    Returns the LATEST assistant message only if it contains req_id,
    otherwise None. Prefer correlate_response for strict multi-field binding.
    """
    if not assistant_messages or not isinstance(assistant_messages, list):
        return None
    latest = assistant_messages[-1]
    if req_id and req_id in (latest or ""):
        return latest
    return None


def correlate_response(assistant_messages, envelope):
    """Find the assistant message that is the correlated response.

    Rules (fail closed, strict):
    - ONLY the LATEST assistant message is eligible to be the response.
    - The latest message must bind ALL FOUR correlation fields:
        REVIEW_REQUEST_ID, REPO, PR, HEAD.
    - Each of the four fields in the latest message must:
        * be present
        * be non-empty
        * exactly equal the corresponding envelope value
    - Any missing, empty, or mismatched field -> reject (returns None).
    - An older assistant message is NEVER accepted, even if it contains this
      request_id, because the latest message did not.

    Returns the matched text or None.
    """
    if not assistant_messages or not isinstance(assistant_messages, list):
        return None
    env = envelope or {}
    req_id = env.get("REVIEW_REQUEST_ID")
    exp_repo = env.get("REPO")
    exp_pr = env.get("PR")
    exp_head = env.get("HEAD")
    if not req_id or not exp_repo or not exp_pr or not exp_head:
        return None
    latest = assistant_messages[-1]
    text = latest or ""
    if req_id not in text:
        return None
    fields = {}
    for line in text.splitlines():
        for key in ("REVIEW_REQUEST_ID", "REPO", "PR", "HEAD"):
            if line.startswith(f"{key}:"):
                fields[key] = line.split(f"{key}:", 1)[1].strip()
    stated_req = fields.get("REVIEW_REQUEST_ID")
    stated_repo = fields.get("REPO")
    stated_pr = fields.get("PR")
    stated_head = fields.get("HEAD")
    # Strict: all four must be present, non-empty, and exactly equal.
    if not stated_req or stated_req != req_id:
        return None
    if not stated_repo or stated_repo != exp_repo:
        return None
    if not stated_pr or stated_pr != exp_pr:
        return None
    if not stated_head or stated_head != exp_head:
        return None
    return text
    return text


def classify_send_result(conversation_users, request_text, req_id):
    """Decide whether a request was actually delivered to the conversation.

    Returns one of:
      ("CONFIRMED_SENT", evidence)
      ("CONFIRMED_NOT_SENT", reason)
      ("AMBIGUOUS", reason)

    - CONFIRMED_SENT: the request_id (or a stable payload snippet) appears in
      a user message, or the request text appears verbatim.
    - CONFIRMED_NOT_SENT: the conversation is readable and the request is
      definitely absent.
    - AMBIGUOUS: the conversation could not be read at all (None / not a list).
    """
    if not isinstance(conversation_users, list):
        return ("AMBIGUOUS", "conversation users unreadable")
    if not conversation_users:
        return ("CONFIRMED_NOT_SENT", "no user messages visible yet; request not found")
    for msg in conversation_users:
        if req_id and req_id in (msg or ""):
            return ("CONFIRMED_SENT", f"request_id {req_id} found in user message")
    snippet = normalize_text(request_text)
    if snippet and len(snippet) > 10:
        for msg in conversation_users:
            if snippet in normalize_text(msg):
                return ("CONFIRMED_SENT", "request payload snippet found in user message")
    return ("CONFIRMED_NOT_SENT", "request_id / payload not found in any user message")


def should_skip_send(conversation_users, req_id):
    """Duplicate-send protection: if the request_id is already in the
    conversation, a previous invocation already sent it -> skip send."""
    if not isinstance(conversation_users, list) or not req_id:
        return False
    return any(req_id in (msg or "") for msg in conversation_users)


# ---------------------------------------------------------------------------
# CDP session (mechanical transport; no judgement)
# ---------------------------------------------------------------------------

class CdpSession:
    """Thin CDP transport over the browser-level websocket."""

    def __init__(self, ws_url):
        self._ws_url = ws_url
        self._ws = None
        self._id = 0

    async def __aenter__(self):
        self._ws = await websockets.connect(self._ws_url, max_size=2**30, open_timeout=10)
        return self

    async def __aexit__(self, *exc):
        if self._ws:
            await self._ws.close()

    async def _cmd(self, method, params=None, session=None):
        self._id += 1
        mid = self._id
        msg = {"id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        if session:
            msg["sessionId"] = session
        await self._ws.send(json.dumps(msg))
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=90)
            data = json.loads(raw)
            if data.get("id") == mid:
                return data

    async def page_targets(self):
        r = await self._cmd("Target.getTargets")
        return [
            t for t in r.get("result", {}).get("targetInfos", [])
            if t.get("type") == "page"
        ]

    async def attach(self, target_id):
        at = await self._cmd("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        return at.get("result", {}).get("sessionId")

    async def eval_js(self, expr, session):
        ev = await self._cmd("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": True,
        }, session=session)
        if "exceptionDetails" in ev.get("result", {}):
            return {"__js_error__": str(ev["result"]["exceptionDetails"])[:300]}
        return ev.get("result", {}).get("result", {}).get("value")

    async def insert_text(self, text, session):
        await self._cmd("Input.insertText", {"text": text}, session=session)

    async def key_combo(self, modifiers, key, code, vk, session):
        await self._cmd("Input.dispatchKeyEvent", {
            "type": "keyDown", "modifiers": modifiers, "key": key, "code": code,
            "windowsVirtualKeyCode": vk,
        }, session=session)
        await self._cmd("Input.dispatchKeyEvent", {
            "type": "keyUp", "modifiers": modifiers, "key": key, "code": code,
            "windowsVirtualKeyCode": vk,
        }, session=session)

    async def reload(self, session):
        await self._cmd("Page.enable", {}, session=session)
        await self._cmd("Page.reload", {"ignoreCache": True}, session=session)


# ---------------------------------------------------------------------------
# DOM probes (JSON-in / JSON-out; the ONLY place that touches page structure)
# ---------------------------------------------------------------------------

class DomProbe:
    """Structured, non-brittle DOM queries. Never dumps the full page."""

    COMPOSER_SELECTORS = (
        "#prompt-textarea",
        '[contenteditable="true"]',
        "textarea[aria-label*='与 ChatGPT 聊天']",
        "main textarea",
    )

    SEND_SELECTORS = (
        'button[data-testid="send-button"]',
        'button[data-testid="composer-send-button"]',
        'button[aria-label="发送提示"]',
        'button[aria-label="Send prompt"]',
        'button[aria-label="Send message"]',
        'form button[type="submit"]',
    )

    PROBE_COMPOSER = """(sels)=>{
      const out=[];
      for (const sel of sels) {
        let el;
        try { el = document.querySelector(sel); } catch(e) { el = null; }
        if (!el) { out.push({sel, found:false}); continue; }
        const r = el.getBoundingClientRect();
        const vis = el.offsetParent !== null && r.width > 0 && r.height > 0;
        const txt = (typeof el.innerText !== 'undefined') ? el.innerText : (el.value || '');
        out.push({sel, found:true, vis, w:Math.round(r.width), h:Math.round(r.height),
                  ce: el.getAttribute('contenteditable'), aria: el.getAttribute('aria-label')||null,
                  textLen: (txt||'').length});
      }
      return out;
    }"""

    PROBE_SEND = """(sels)=>{
      const out=[];
      for (const sel of sels) {
        let el;
        try { el = document.querySelector(sel); } catch(e) { el = null; }
        if (!el) { out.push({sel, found:false}); continue; }
        const r = el.getBoundingClientRect();
        const vis = el.offsetParent !== null && r.width > 0 && r.height > 0;
        out.push({sel, found:true, vis, disabled: !!el.disabled, w:Math.round(r.width)});
      }
      return out;
    }"""

    PROBE_CONVERSATION = """()=>{
      const users = Array.from(document.querySelectorAll('[data-message-author-role="user"]'))
                         .map(m => m.innerText || '');
      const asst = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'))
                         .map(m => m.innerText || '');
      const stopBtn = !!Array.from(document.querySelectorAll('button'))
                              .find(b => /停止生成|Stop generating/.test(b.innerText || ''));
      return {users, asst, stopBtn};
    }"""

    PROBE_FOCUS_COMPOSER = """(sels)=>{
      for (const sel of sels) {
        const el = document.querySelector(sel);
        if (el && el.offsetParent !== null) { el.focus(); return sel; }
      }
      return null;
    }"""

    PROBE_CLICK_SEND = """(sels)=>{
      for (const sel of sels) {
        const el = document.querySelector(sel);
        if (el && !el.disabled && el.offsetParent !== null) { el.click(); return sel; }
      }
      return null;
    }"""

    PROBE_CURRENT_URL = "(()=>window.location.href)()"

    def __init__(self, session, sid):
        self.session = session
        self.sid = sid

    async def probe(self, js_fn, args):
        expr = f"({js_fn})({json.dumps(args)})"
        res = await self.session.eval_js(expr, self.sid)
        if isinstance(res, dict) and res.get("__js_error__"):
            raise RuntimeError(f"JS probe error: {res['__js_error__']}")
        return res

    async def composers(self):
        return await self.probe(self.PROBE_COMPOSER, self.COMPOSER_SELECTORS)

    async def send_controls(self):
        return await self.probe(self.PROBE_SEND, self.SEND_SELECTORS)

    async def conversation(self):
        return await self.probe(self.PROBE_CONVERSATION, [])

    async def focus_composer(self):
        return await self.probe(self.PROBE_FOCUS_COMPOSER, self.COMPOSER_SELECTORS)

    async def click_send(self):
        return await self.probe(self.PROBE_CLICK_SEND, self.SEND_SELECTORS)

    async def current_url(self):
        return await self.session.eval_js(self.PROBE_CURRENT_URL, self.sid)


# ---------------------------------------------------------------------------
# Send flow state machine
# ---------------------------------------------------------------------------

class SendFlowError(Exception):
    """Fail-closed error carrying the stage and a reason."""

    def __init__(self, stage, reason):
        super().__init__(f"[{stage}] {reason}")
        self.stage = stage
        self.reason = reason


class SendFlow:
    """Explicit send state machine.

    Stages:
      LOCATE_CONVERSATION -> LOCATE_COMPOSER -> FOCUS -> INSERT_TEXT
      -> VERIFY_TEXT_PRESENT -> LOCATE_SEND_CONTROL -> WAIT_UNTIL_ENABLED
      -> CLICK_SEND -> VERIFY_REQUEST_APPEARED -> WAIT_ASSISTANT_RESPONSE
      -> VERIFY_COMPLETION -> EXTRACT_CORRELATED_RESPONSE

    Every stage has a bounded timeout and fails closed with an explicit error.
    After CLICK_SEND the flow reconciles against the conversation before any
    possible retry; a retry is only attempted when CONFIRMED_NOT_SENT.
    """

    STAGE_TIMEOUTS = {
        "LOCATE_CONVERSATION": 10,
        "LOCATE_COMPOSER": 30,
        "WAIT_SEND_ENABLED": 20,
        "VERIFY_REQUEST_APPEARED": 30,
        "WAIT_ASSISTANT_RESPONSE": 180,
    }

    def __init__(self, probe, reviewer_url, timeout=None, max_send_attempts=2,
                 poll_interval=2.0, stage_timeouts=None):
        self.probe = probe
        self.reviewer_url = reviewer_url
        self.timeout = timeout or self.stage_timeouts["WAIT_ASSISTANT_RESPONSE"]
        self.max_send_attempts = max_send_attempts
        self.poll_interval = poll_interval
        self.stage_timeouts = dict(self.STAGE_TIMEOUTS)
        if stage_timeouts:
            self.stage_timeouts.update(stage_timeouts)

    async def _deadline(self, stage):
        return time.time() + self.stage_timeouts.get(stage, 30)

    async def verify_conversation_identity(self):
        """Re-read the attached page URL and confirm it still matches the
        configured reviewer conversation exactly. Fails closed on drift."""
        url = await self.probe.current_url()
        if not target_matches_reviewer(url, self.reviewer_url):
            raise SendFlowError(
                "CONVERSATION_IDENTITY_DRIFT",
                f"attached page no longer matches reviewer conversation "
                f"(configured {conversation_id_from_url(self.reviewer_url)!r}, "
                f"current {conversation_id_from_url(url)!r})")
        return url

    async def _locate_visible_composer(self):
        deadline = time.time() + self.stage_timeouts["LOCATE_COMPOSER"]
        while time.time() < deadline:
            comps = await self.probe.composers()
            for c in comps or []:
                if c.get("found") and c.get("vis"):
                    return c
            await asyncio.sleep(1)
        raise SendFlowError("LOCATE_COMPOSER",
                            "no visible composer found (contenteditable / textarea)")

    async def _insert_text_and_verify(self, text):
        deadline = time.time() + self.stage_timeouts["LOCATE_COMPOSER"]
        norm_target = normalize_text(text)
        while time.time() < deadline:
            focused = await self.probe.focus_composer()
            if not focused:
                raise SendFlowError("FOCUS", "could not focus any composer")
            # clear existing content, then type real text via CDP Input.insertText
            await self.probe.session.key_combo(
                4, "a", "KeyA", 65, self.probe.sid)  # Cmd+A select all
            await self.probe.session.key_combo(
                0, "Backspace", "Backspace", 8, self.probe.sid)  # clear
            await asyncio.sleep(0.3)
            await self.probe.session.insert_text(text, self.probe.sid)
            await asyncio.sleep(0.8)
            current = await self._composer_text()
            if current and normalize_text(current) == norm_target:
                return
        raise SendFlowError("VERIFY_TEXT_PRESENT",
                            "typed text not verified present in composer")

    async def _composer_text(self):
        # Read current visible composer text via the probe's conversation-agnostic path.
        comps = await self.probe.composers()
        for c in comps or []:
            if c.get("found") and c.get("vis"):
                sel = c.get("sel")
                res = await self.probe.session.eval_js(
                    f"(()=>{{const e=document.querySelector({json.dumps(sel)});"
                    f"return e ? ((e.innerText!==undefined)?e.innerText:(e.value||'')) : '';}})()",
                    self.probe.sid,
                )
                return res or ""
        return ""

    async def _locate_enabled_send(self):
        deadline = time.time() + self.stage_timeouts["WAIT_SEND_ENABLED"]
        while time.time() < deadline:
            controls = await self.probe.send_controls()
            for c in controls or []:
                if c.get("found") and c.get("vis") and not c.get("disabled"):
                    return c
            await asyncio.sleep(1)
        raise SendFlowError("WAIT_UNTIL_ENABLED",
                            "send control never became enabled (always disabled / hidden)")

    async def run(self, envelope, request_text):
        """Execute the full send flow. Returns the correlated response text."""
        req_id = envelope["REVIEW_REQUEST_ID"]

        # LOCATE_CONVERSATION + pre-send duplicate check
        await self.verify_conversation_identity()
        conv = await self.probe.conversation()
        if conv and should_skip_send(conv.get("users"), req_id):
            return await self._wait_for_response(envelope)

        # Full send path
        attempt = 0
        while attempt < self.max_send_attempts:
            attempt += 1
            await self.verify_conversation_identity()
            await self._locate_visible_composer()
            await self._insert_text_and_verify(request_text)
            await self._locate_enabled_send()
            # REVERIFY_CONVERSATION immediately before click: if the tab
            # was switched / reused during composer interaction, fail closed.
            await self.verify_conversation_identity()
            clicked = await self.probe.click_send()
            if not clicked:
                raise SendFlowError("CLICK_SEND", "send control disappeared before click")

            # Identity re-verification after the send mutation
            await self.verify_conversation_identity()

            # VERIFY_REQUEST_APPEARED (reconcile before any retry)
            verdict, evidence = await self._reconcile_send(request_text, req_id)
            if verdict == "CONFIRMED_SENT":
                return await self._wait_for_response(envelope)
            if verdict == "AMBIGUOUS":
                raise SendFlowError("UNKNOWN_RESULT",
                                    f"send result ambiguous after click: {evidence}")
            if attempt < self.max_send_attempts:
                await asyncio.sleep(self.poll_interval)
                continue
            raise SendFlowError("CLICK_SEND",
                                f"confirmed not sent after {self.max_send_attempts} attempts")

        raise SendFlowError("CLICK_SEND", "exhausted send attempts")

    async def _reconcile_send(self, request_text, req_id):
        deadline = time.time() + self.stage_timeouts["VERIFY_REQUEST_APPEARED"]
        while time.time() < deadline:
            conv = await self.probe.conversation()
            verdict, evidence = classify_send_result(
                (conv or {}).get("users"), request_text, req_id)
            if verdict in ("CONFIRMED_SENT", "AMBIGUOUS"):
                return verdict, evidence
            await asyncio.sleep(self.poll_interval)
        return ("CONFIRMED_NOT_SENT",
                "request never appeared in conversation within timeout")

    async def _wait_for_response(self, envelope):
        deadline = time.time() + self.timeout
        last_seen = None
        req_id = envelope.get("REVIEW_REQUEST_ID")
        while time.time() < deadline:
            await self.verify_conversation_identity()
            conv = await self.probe.conversation()
            asst = (conv or {}).get("asst") or []
            matched = correlate_response(asst, envelope)
            if matched:
                stop = bool(conv and conv.get("stopBtn"))
                if not stop:
                    if matched == last_seen:
                        return matched  # stable across a poll -> complete
                    last_seen = matched
            await asyncio.sleep(self.poll_interval)
        raise SendFlowError("WAIT_ASSISTANT_RESPONSE",
                            f"timed out waiting for correlated response for {req_id}")


# ---------------------------------------------------------------------------
# Orchestration + CLI
# ---------------------------------------------------------------------------

async def run_relay(args):
    # 1. Read + validate request envelope
    if not os.path.exists(args.request_file):
        print(f"Error: Request file {args.request_file} not found.")
        return 1
    with open(args.request_file, "r") as f:
        request_text = f.read()

    envelope = parse_envelope(request_text)
    missing = [k for k, v in envelope.items() if not v]
    if missing:
        print(f"Error: missing or empty fields in request file: {missing}. Fail closed.")
        return 1

    repo = envelope["REPO"]
    req_id = envelope["REVIEW_REQUEST_ID"]

    # 2. Config routing (trusted routing only)
    if not os.path.exists(args.config_file):
        print(f"Error: Config file {args.config_file} not found.")
        return 1
    with open(args.config_file, "r") as f:
        config = json.load(f)
    route = config.get("routes", {}).get(repo)
    if not route:
        print(f"Error: No trusted route configured for repo {repo}. Fail closed.")
        return 1
    gpt_url = route.get("conversation_url")
    cdp_port = route.get("cdp_port")
    if not gpt_url or not cdp_port:
        print("Error: Incomplete route configuration (need conversation_url and cdp_port).")
        return 1

    if args.dry_run:
        print(f"[DRY-RUN] Would route {repo} to CDP port {cdp_port} at URL {gpt_url}")
        print(f"[DRY-RUN] Sending Payload:\n{request_text}")
        print(f"[DRY-RUN] Waiting for response with ID: {req_id}")
        return 0

    # 3. CDP connect
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=8) as r:
            ws_url = json.loads(r.read().decode()).get("webSocketDebuggerUrl", "")
    except Exception as e:
        print(f"Error connecting to CDP on port {cdp_port}: {e}")
        return 1

    async with CdpSession(ws_url) as session:
        # LOCATE_CONVERSATION: strict Conversation Identity Binding.
        # Exactly one tab whose normalized URL matches the configured reviewer
        # conversation. Never a generic ChatGPT tab, never a historical
        # conversation, never a substring match, never a title match.
        pages = await session.page_targets()
        try:
            target = resolve_reviewer_target(pages, gpt_url)
        except ConversationIdentityError as e:
            print(f"Error: {e}")
            return 1
        reviewer_cid = conversation_id_from_url(gpt_url)
        matched_cid = conversation_id_from_url(target["url"])
        print(f"EXPECTED_CONVERSATION_ID: {reviewer_cid}")
        print(f"MATCHED_CONVERSATION_ID: {matched_cid}")
        if reviewer_cid != matched_cid:
            print("STOP: CONVERSATION_ID_MISMATCH")
            return 1
        sid = await session.attach(target["targetId"])

        probe = DomProbe(session, sid)
        timeout = getattr(args, "timeout", None) or 180
        flow = SendFlow(probe, reviewer_url=gpt_url, timeout=timeout,
                        max_send_attempts=getattr(args, "max_send_attempts", 2))

        # Second identity check after attach: read the actual page URL again.
        try:
            await flow.verify_conversation_identity()
        except SendFlowError as e:
            print(f"Error: {e}")
            return 1

        try:
            final_text = await flow.run(envelope, request_text)
        except SendFlowError as e:
            print(f"Error: {e}")
            return 1

    with open(args.output_file, "w") as f:
        f.write(final_text)
    print(f"Success: Wrote correlated review to {args.output_file}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Neutral Relay Transport for Agent-Ops")
    parser.add_argument("--request-file", required=True, help="Path to the review request payload file")
    parser.add_argument("--output-file", required=True, help="Path to write the GPT review response")
    parser.add_argument("--config-file", default=os.path.expanduser("~/.agentops/relay/config.json"),
                        help="Path to the routing config.json")
    parser.add_argument("--dry-run", action="store_true", help="Simulate routing without CDP execution")
    parser.add_argument("--timeout", type=int, default=180, help="Max seconds to wait for the response")
    parser.add_argument("--max-send-attempts", type=int, default=2,
                        help="Max CLICK_SEND attempts when confirmed-not-sent")
    args = parser.parse_args()
    sys.exit(asyncio.run(run_relay(args)))


if __name__ == "__main__":
    main()
