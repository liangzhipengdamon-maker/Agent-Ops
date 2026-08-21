#!/usr/import/env python3
import argparse
import json
import os
import sys
import time
import urllib.request
import websockets
import asyncio

# Canonical local routing authority for GovernLoop Minimal Transport.
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.governloop/relay/config.json")

# Two-stage finalization settle.
#   NORMAL       (no soft streaming/busy markers): short settle.
#   CONSERVATIVE (one or more soft markers remain): long settle so a brief
#                generation pause cannot be mistaken for "done".
NORMAL_STABLE_READS = 3
NORMAL_SETTLE_SECONDS = 4.0
CONSERVATIVE_STABLE_READS = 6
CONSERVATIVE_SETTLE_SECONDS = 30.0


class ResponseCompletionTracker:
    """Two-stage finalization settle for a correlated Assistant turn.

    Stage selection is driven by the *current* soft-generation signal (leftover
    stop-button / streaming / aria-busy DOM markers). Those markers are SOFT
    only and are NEVER a hard veto. A text change is the hard live-generation
    signal and always blocks finalization, resetting both the settle timer and
    the stable-read counter.

    NORMAL (no soft markers present):
        - assistant text stable for >= NORMAL_SETTLE_SECONDS
        - >= NORMAL_STABLE_READS consecutive identical reads
        => finalize

    CONSERVATIVE (one or more soft markers remain):
        - assistant text stable for >= CONSERVATIVE_SETTLE_SECONDS
        - >= CONSERVATIVE_STABLE_READS consecutive identical reads
        => finalize

    Rules:
        - any assistant text change resets the settle timer + stable-read count
        - if soft markers clear, NORMAL settle applies to the already-stable text
        - stale markers must not block forever (CONSERVATIVE still finalizes)
        - text still changing always blocks
        - timeout (enforced by the caller) remains fail-closed
        - the response is NOT required to echo REVIEW_REQUEST_ID (generic transport)
    """

    def __init__(
        self,
        normal_stable_reads=NORMAL_STABLE_READS,
        normal_settle_seconds=NORMAL_SETTLE_SECONDS,
        conservative_stable_reads=CONSERVATIVE_STABLE_READS,
        conservative_settle_seconds=CONSERVATIVE_SETTLE_SECONDS,
    ):
        self.normal_stable_reads = normal_stable_reads
        self.normal_settle_seconds = normal_settle_seconds
        self.conservative_stable_reads = conservative_stable_reads
        self.conservative_settle_seconds = conservative_settle_seconds
        self.last_text = None
        self.stable_reads = 0
        self.stable_since = None

    def reset(self):
        self.last_text = None
        self.stable_reads = 0
        self.stable_since = None

    def observe(self, snapshot, user_count_before, req_id, now=None):
        now = time.monotonic() if now is None else now
        snapshot = snapshot if isinstance(snapshot, dict) else {}

        try:
            user_count = int(snapshot.get("userCount") or 0)
        except (TypeError, ValueError):
            user_count = 0

        last_user_text = str(snapshot.get("lastUserText") or "").strip()
        text = str(snapshot.get("text") or "").strip()
        has_assistant = bool(snapshot.get("hasAssistant"))
        soft_generating = bool(snapshot.get("softGenerating"))

        # Correlation: this send must have produced a new user turn followed by
        # an assistant turn. The response itself is NOT required to echo
        # REVIEW_REQUEST_ID (supports generic transport).
        user_added = (user_count > user_count_before) or (
            bool(req_id) and req_id in last_user_text
        )

        if not (user_added and has_assistant and text):
            self.reset()
            return False, ""

        if text != self.last_text:
            # Hard live-generation evidence: reset settle + stable-read count.
            self.last_text = text
            self.stable_reads = 1
            self.stable_since = now
            return False, ""

        self.stable_reads += 1
        stable_for = max(0.0, now - (self.stable_since if self.stable_since is not None else now))

        if soft_generating:
            required_reads = self.conservative_stable_reads
            required_settle = self.conservative_settle_seconds
        else:
            required_reads = self.normal_stable_reads
            required_settle = self.normal_settle_seconds

        if self.stable_reads >= required_reads and stable_for >= required_settle:
            return True, text

        return False, ""


class AttachmentUploader:
    """Upload evidence attachments through the conversation file input.

    CDP mechanics are injected as async callables so the decision logic is
    unit-testable without a live browser:

      find_input()                 -> file-input node id (or None)
      set_files(node_id, abs_path) -> awaitable; raises on transport failure
      is_visible(filename)         -> awaitable bool (name visible in composer)

    Fail-closed: a missing file, absent file input, upload error, or a file
    name that never becomes visible all yield (False, reason). The caller MUST
    NOT send the request text or write a response when any attachment fails.
    """

    def __init__(
        self,
        find_input,
        set_files,
        is_visible,
        visibility_retries=15,
        retry_delay=1.0,
    ):
        self.find_input = find_input
        self.set_files = set_files
        self.is_visible = is_visible
        self.visibility_retries = visibility_retries
        self.retry_delay = retry_delay

    async def upload(self, path):
        """Return (ok, reason). reason is None on success."""
        if not os.path.exists(path):
            return False, "missing-file"
        node_id = await self.find_input()
        if not node_id:
            return False, "no-file-input"
        try:
            await self.set_files(node_id, os.path.abspath(path))
        except Exception as exc:  # fail-closed on transport/upload errors
            return False, f"upload-error:{exc}"
        base = os.path.basename(path)
        for _ in range(self.visibility_retries):
            await asyncio.sleep(self.retry_delay)
            if await self.is_visible(base):
                return True, None
        return False, "not-visible"


async def upload_attachments(uploader, paths):
    """Upload every evidence attachment; stop at the first failure.

    Returns (ok, failed_path, reason). Never returns ok=True when any
    attachment failed to upload - callers must treat failure as
    CHECKPOINT_DELIVERY_INCOMPLETE and must not proceed to send text or write
    a response (no false COMPLETE).
    """
    for ap in paths:
        ok, reason = await uploader.upload(ap)
        if not ok:
            print(f"ATTACH_FAIL {reason}: {ap}")
            return False, ap, reason
        print(f"ATTACHED: {ap}")
    return True, None, None


async def run_relay(args):
    # 1. Read request file
    if not os.path.exists(args.request_file):
        print(f"Error: Request file {args.request_file} not found.")
        return 1
        
    with open(args.request_file, "r") as f:
        request_text = f.read()

    # Extract REPO and REVIEW_REQUEST_ID for routing and anti-crosstalk
    repo = None
    req_id = None
    for line in request_text.split('\n'):
        if line.startswith("REPO:"):
            repo = line.split("REPO:")[1].strip()
        elif line.startswith("REVIEW_REQUEST_ID:"):
            req_id = line.split("REVIEW_REQUEST_ID:")[1].strip()

    if not repo:
        print("Error: REPO field not found in request file. Fail closed.")
        return 1
    if not req_id:
        print("Error: REVIEW_REQUEST_ID field not found in request file. Fail closed.")
        return 1

    # 2. Config Routing (Trusted routing only)
    config_file = args.config_file
    if not os.path.exists(config_file):
        print(f"Error: Config file {config_file} not found.")
        return 1
        
    with open(config_file, "r") as f:
        config = json.load(f)
        
    route = config.get("routes", {}).get(repo)
    if not route:
        print(f"Error: No trusted route configured for repo {repo}. Fail closed.")
        return 1

    # Session-level overrides (never written back to config): the conversation
    # URL is task/session state. The repo must still be a trusted configured
    # route, but its conversation target may be overridden for this run only
    # (ask the user once per session; never persist a permanent binding).
    gpt_url = args.conversation_url or route.get("conversation_url")
    cdp_port = args.cdp_port or route.get("cdp_port")

    if not gpt_url or not cdp_port:
        print("Error: Incomplete route configuration. Need conversation_url and cdp_port.")
        return 1

    # In DRY-RUN mode, just print what we would do and simulate success
    if args.dry_run:
        print(f"[DRY-RUN] Would route {repo} to CDP port {cdp_port} at URL {gpt_url}")
        print(f"[DRY-RUN] Sending Payload:\n{request_text}")
        print(f"[DRY-RUN] Waiting for response with ID: {req_id}")
        
        # Simulate an external response write
        mock_response = (
            f"REVIEW_REQUEST_ID: {req_id}\n"
            "VERDICT: PASS\n"
            f"REPO: {repo}\n"
            "PR: mock\n"
            "HEAD: mock\n"
            "SUMMARY: Dry run test\n"
            "ACTIONS: None\n"
        )
        with open(args.output_file, "w") as f:
            f.write(mock_response)
        return 0

    # 3. Transport via CDP
    try:
        req = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=8)
        ws_url = json.loads(req.read().decode()).get("webSocketDebuggerUrl", "")
    except Exception as e:
        print(f"Error connecting to CDP on port {cdp_port}: {e}")
        return 1
        
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
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(raw)
                if data.get("id") == mid:
                    return data

        # Find specific conversation tab
        r = await cmd("Target.getTargets")
        target = next((t for t in r.get("result", {}).get("targetInfos", [])
                       if t.get("type") == "page" and gpt_url in (t.get("url") or "")), None)
                       
        if not target:
            print("Error: Target conversation URL not open in browser.")
            return 1
            
        at = await cmd("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})
        sid = at.get("result", {}).get("sessionId")

        async def js(expr):
            ev = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True}, session=sid)
            return ev.get("result", {}).get("result", {}).get("value")

        await cmd("Page.enable", {}, session=sid)

        # ── OPTIONAL: upload evidence attachments before sending text ────────
        # Each --attachment is uploaded through the ChatGPT file input via CDP
        # DOM.setFileInputFiles (no user gesture needed). Attachment readiness is
        # verified by waiting for the file name to appear in the composer DOM.
        # All uploads happen inside this single attached session, so text and
        # attachments always go to the SAME bound conversation.
        async def _find_file_input():
            await cmd("DOM.enable", {}, session=sid)
            doc = await cmd("DOM.getDocument", {"depth": -1}, session=sid)
            root = doc.get("result", {}).get("root", {}).get("nodeId")
            q = await cmd("DOM.querySelector",
                          {"nodeId": root, "selector": "input[type=file]"},
                          session=sid)
            return q.get("result", {}).get("nodeId")

        async def _set_files(node_id, abs_path):
            await cmd("DOM.setFileInputFiles",
                      {"nodeId": node_id, "files": [abs_path]},
                      session=sid)

        async def _is_visible(base):
            seen = await js("(()=>{const t=(document.querySelector('[contenteditable=true]')||{}).innerText||'';const b=document.body.innerText||'';return t+' '+b;})()")
            return base in (seen or "")

        uploader = AttachmentUploader(_find_file_input, _set_files, _is_visible)
        ok, failed_path, reason = await upload_attachments(uploader, args.attachment or [])
        if not ok:
            # CHECKPOINT_DELIVERY_INCOMPLETE: never proceed to send the text or
            # write a response when any required attachment failed to upload.
            return 1
        await asyncio.sleep(1)

        # Capture the existing user-turn count before sending. The response is
        # correlated to the assistant turn that follows the user turn created
        # by this send, so the pre-send state that must change is the count of
        # user turns (not assistant turns).
        user_count_before = await js("(()=>document.querySelectorAll('[data-message-author-role=\\'user\\']').length)()")
        try:
            user_count_before = int(user_count_before or 0)
        except (TypeError, ValueError):
            user_count_before = 0

        # Inject request text using exact DOM interactions
        esc_text = json.dumps(request_text)
        await js(f"(()=>{{const e=document.querySelector('[contenteditable=true]');if(!e)return false;e.focus();e.innerHTML='';e.innerText={esc_text};e.dispatchEvent(new Event('input',{{bubbles:true}}));return true}})()")
        await asyncio.sleep(1)
        
        # Click send
        clk = await js("(()=>{const b=document.querySelector('button[data-testid=\\'send-button\\']'); if(b && !b.disabled){b.click(); return true;} return false;})()")
        if not clk:
            print("Error: Send button not found or disabled.")
            return 1

        # Poll for the assistant response following the user turn created by
        # this send. Correlation remains user-turn -> following Assistant turn.
        # Completion is text-first: a text change is hard evidence that output
        # is still live and restarts the settle window. ChatGPT DOM stop/busy/
        # streaming markers are only soft evidence because they may remain stale
        # after a visibly complete response. Soft markers therefore require a
        # longer stable-text settle window, but cannot block finalization forever.
        deadline = time.time() + args.wait_timeout
        found_response = False
        final_text = ""
        completion = ResponseCompletionTracker()
        while time.time() < deadline:
            snapshot = await js("""(()=>{
                const roles = Array.from(document.querySelectorAll('[data-message-author-role]'));
                const users = roles.filter(n => n.getAttribute('data-message-author-role') === 'user');
                const lastUser = users.length ? users[users.length - 1] : null;
                const lastUserText = lastUser ? ((lastUser.innerText || lastUser.textContent || '').trim()) : '';
                let assistant = null;
                if (lastUser) {
                    const idx = roles.indexOf(lastUser);
                    for (let i = idx + 1; i < roles.length; i++) {
                        if (roles[i].getAttribute('data-message-author-role') === 'assistant') {
                            assistant = roles[i];
                            break;
                        }
                    }
                }
                const text = assistant ? ((assistant.innerText || assistant.textContent || '').trim()) : '';
                const stop = document.querySelector('button[data-testid="stop-button"], button[data-testid="stop-generation"], button[aria-label*="Stop"], button[aria-label*="停止"]');
                const streaming = !!(assistant && (
                    assistant.matches('.streaming-animation') ||
                    assistant.querySelector('.streaming-animation') ||
                    assistant.getAttribute('data-is-streaming') === 'true' ||
                    assistant.getAttribute('aria-busy') === 'true'
                ));
                return {
                    userCount:users.length,
                    lastUserText:lastUserText,
                    text:text,
                    hasAssistant:!!assistant,
                    softGenerating:(!!stop || streaming),
                    stopPresent:!!stop,
                    streamingMarker:streaming
                };
            })()""")

            complete, settled_text = completion.observe(
                snapshot,
                user_count_before=user_count_before,
                req_id=req_id,
            )
            if complete:
                final_text = settled_text
                found_response = True
                break

            await asyncio.sleep(2)
            
        if not found_response:
            print(f"Error: Timed out after {args.wait_timeout}s waiting for a new stable Assistant response to settle.")
            return 1
            
        with open(args.output_file, "w") as f:
            f.write(final_text)
            
        print(f"Success: Wrote response to {args.output_file}")
        return 0

def main():
    parser = argparse.ArgumentParser(description="GovernLoop Neutral Relay Transport")
    parser.add_argument("--request-file", required=True, help="Path to the review request payload file")
    parser.add_argument("--output-file", required=True, help="Path to write the GPT review response")
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_PATH, help=f"Path to the routing config.json (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--wait-timeout", type=int, default=900, help="Seconds to wait for the new Assistant turn to finish streaming and stabilize (default: 900)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate routing without CDP execution")
    parser.add_argument("--attachment", action="append", default=[],
                        help="evidence file to upload to the conversation before sending "
                             "the request text (repeatable). The file is uploaded through the "
                             "ChatGPT file input via CDP and its readiness is verified.")
    parser.add_argument("--conversation-url", default=None,
                        help="session-level ChatGPT conversation URL override for this run "
                             "(ask the user once per session; never written to config)")
    parser.add_argument("--cdp-port", type=int, default=None,
                        help="session-level CDP port override for this run "
                             "(never written to config)")
    args = parser.parse_args()
    sys.exit(asyncio.run(run_relay(args)))

if __name__ == "__main__":
    main()
