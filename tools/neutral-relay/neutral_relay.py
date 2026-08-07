#!/usr/bin/env python3
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

    # In DRY-RUN mode, just print what we would do and verify the payload
    if args.dry_run:
        print(f"[DRY-RUN] Would route {repo} to CDP port {cdp_port} at URL {gpt_url}")
        print(f"[DRY-RUN] Sending Payload:\n{request_text}")
        print(f"[DRY-RUN] Waiting for response with ID: {req_id}")
        # Dry-run MUST NOT generate a fake review or write PASS. It only validates the transport config.
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

        # Inject request text using exact DOM interactions
        esc_text = json.dumps(request_text)
        await js(f"(()=>{{const e=document.querySelector('[contenteditable=true]');if(!e)return false;e.focus();e.innerHTML='';e.innerText={esc_text};e.dispatchEvent(new Event('input',{{bubbles:true}}));return true}})()")
        await asyncio.sleep(1)
        
        # Click send
        clk = await js("(()=>{const b=document.querySelector('button[data-testid=\\'send-button\\']'); if(b && !b.disabled){b.click(); return true;} return false;})()")
        if not clk:
            print("Error: Send button not found or disabled.")
            return 1

        # Poll for completion and check for request ID in the LATEST assistant message
        deadline = time.time() + 180
        found_response = False
        final_text = ""
        while time.time() < deadline:
            # First check if the page is still generating
            is_generating = bool(await js("(()=>{const btns=Array.from(document.querySelectorAll('button')); return btns.some(b=>b.innerText.includes('停止生成') || b.innerText.includes('Stop generating'));})()"))
            if is_generating:
                await asyncio.sleep(3)
                continue
            
            # Check for the latest assistant message specifically
            latest_assistant_text = str(await js("(()=>{const msgs=Array.from(document.querySelectorAll('[data-message-author-role=\"assistant\"]')); if(msgs.length===0) return ''; return msgs[msgs.length-1].innerText||'';})()"))
            
            if req_id in latest_assistant_text:
                final_text = latest_assistant_text
                found_response = True
                break
            await asyncio.sleep(3)
            
        if not found_response:
            print("Error: Timed out waiting for Assistant reply or Request ID not found in the latest Assistant reply.")
            return 1
            
        # Extract the relevant block strictly (only the latest assistant message, not history)
        with open(args.output_file, "w") as f:
            f.write(final_text)
            
        print(f"Success: Wrote review to {args.output_file}")
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
