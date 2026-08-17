#!/usr/import/env python3
import argparse
import json
import os
import sys
import time
import urllib.request
import websockets
import asyncio

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

    gpt_url = route.get("conversation_url")
    cdp_port = route.get("cdp_port")
    
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

        # Capture the existing assistant-turn count before sending so the
        # response can be identified without requiring GPT to echo routing fields.
        assistant_count_before = await js("(()=>document.querySelectorAll('[data-message-author-role=\\'assistant\\']').length)()")
        try:
            assistant_count_before = int(assistant_count_before or 0)
        except (TypeError, ValueError):
            assistant_count_before = 0

        # Inject request text using exact DOM interactions
        esc_text = json.dumps(request_text)
        await js(f"(()=>{{const e=document.querySelector('[contenteditable=true]');if(!e)return false;e.focus();e.innerHTML='';e.innerText={esc_text};e.dispatchEvent(new Event('input',{{bubbles:true}}));return true}})()")
        await asyncio.sleep(1)
        
        # Click send
        clk = await js("(()=>{const b=document.querySelector('button[data-testid=\\'send-button\\']'); if(b && !b.disabled){b.click(); return true;} return false;})()")
        if not clk:
            print("Error: Send button not found or disabled.")
            return 1

        # Poll the assistant turn created by this send. Modern ChatGPT no longer
        # exposes the historical 'Reply actions'/'回复操作' completion marker, and
        # ordinary natural-language responses should not be forced to echo the
        # REVIEW_REQUEST_ID. A response is complete only after the new assistant
        # turn has stopped streaming and its text is stable across three reads.
        deadline = time.time() + 180
        found_response = False
        final_text = ""
        last_text = None
        stable_reads = 0
        while time.time() < deadline:
            snapshot = await js("""(()=>{
                const nodes = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
                const last = nodes.length ? nodes[nodes.length - 1] : null;
                const text = last ? ((last.innerText || last.textContent || '').trim()) : '';
                const stop = document.querySelector('button[data-testid="stop-button"], button[data-testid="stop-generation"], button[aria-label*="Stop"], button[aria-label*="停止"]');
                const streaming = !!(last && (
                    last.matches('.streaming-animation') ||
                    last.querySelector('.streaming-animation') ||
                    last.getAttribute('data-is-streaming') === 'true' ||
                    last.getAttribute('aria-busy') === 'true'
                ));
                return {count:nodes.length, text:text, generating:(!!stop || streaming), streaming:streaming};
            })()""")
            snapshot = snapshot if isinstance(snapshot, dict) else {}
            count = int(snapshot.get("count") or 0)
            text = str(snapshot.get("text") or "").strip()
            generating = bool(snapshot.get("generating"))

            if count > assistant_count_before and text and not generating:
                if text == last_text:
                    stable_reads += 1
                else:
                    last_text = text
                    stable_reads = 1
                if stable_reads >= 3:
                    final_text = text
                    found_response = True
                    break
            else:
                last_text = None
                stable_reads = 0

            await asyncio.sleep(2)
            
        if not found_response:
            print("Error: Timed out waiting for a new stable Assistant response after streaming ended.")
            return 1
            
        with open(args.output_file, "w") as f:
            f.write(final_text)
            
        print(f"Success: Wrote response to {args.output_file}")
        return 0

def main():
    parser = argparse.ArgumentParser(description="Neutral Relay Transport for Agent-Ops")
    parser.add_argument("--request-file", required=True, help="Path to the review request payload file")
    parser.add_argument("--output-file", required=True, help="Path to write the GPT review response")
    parser.add_argument("--config-file", default=os.path.expanduser("~/.agentops/relay/config.json"), help="Path to the routing config.json")
    parser.add_argument("--dry-run", action="store_true", help="Simulate routing without CDP execution")
    args = parser.parse_args()
    sys.exit(asyncio.run(run_relay(args)))

if __name__ == "__main__":
    main()
