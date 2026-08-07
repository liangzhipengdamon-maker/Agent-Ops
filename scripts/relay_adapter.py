import json
import os
import sys
import argparse
import uuid
import subprocess
import time

def get_bridge_dir():
    return os.environ.get("AGENT_BRIDGE_DIR", ".agent-bridge")

def get_status_file():
    return os.path.join(get_bridge_dir(), "status.json")

def get_review_file():
    return os.path.join(get_bridge_dir(), "gpt-review.md")

def get_request_file():
    return os.path.join(get_bridge_dir(), "request.txt")

DEFAULT_PROFILE = "profiles/agentops.json"

import jsonschema

def load_profile(profile_path):
    if not os.path.exists(profile_path):
        print(f"STOP_AND_WAIT: Profile not found at {profile_path}")
        sys.exit(1)
        
    try:
        with open(profile_path, "r") as f:
            profile_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"STOP_AND_WAIT: Profile JSON malformed: {e}")
        sys.exit(1)
        
    schema_path = os.path.join(os.path.dirname(__file__), "..", "docs", "schemas", "project_profile.schema.json")
    if not os.path.exists(schema_path):
        print(f"STOP_AND_WAIT: Schema not found at {schema_path}")
        sys.exit(1)
        
    try:
        with open(schema_path, "r") as sf:
            schema = json.load(sf)
    except json.JSONDecodeError as e:
        print(f"STOP_AND_WAIT: Schema JSON malformed: {e}")
        sys.exit(1)
        
    try:
        jsonschema.validate(instance=profile_data, schema=schema)
    except jsonschema.exceptions.ValidationError as e:
        print(f"STOP_AND_WAIT: Profile validation failed: {e}")
        sys.exit(1)
            
    return profile_data

def get_canonical_repo(profile):
    return profile.get("github", {}).get("repository")

ALLOWED_STATES = {
    "IDLE",
    "REVIEW_REQUESTED",
    "WAITING_FOR_REVIEW",
    "CHANGES_REQUESTED",
    "BUILDER_FIXING",
    "REVIEW_REQUESTED_AGAIN",
    "BLOCKED",
    "WAITING_PO_AUTH",
    "DONE"
}

def load_status():
    sf = get_status_file()
    if not os.path.exists(sf):
        return None
    with open(sf, "r") as f:
        return json.load(f)

def save_status(data):
    bd = get_bridge_dir()
    os.makedirs(bd, exist_ok=True)
    with open(get_status_file(), "w") as f:
        json.dump(data, f, indent=2)

def handle_review_request(profile):
    status = load_status()
    if not status:
        print("No status.json found.")
        return

    required_keys = ["protocol_version", "state", "repo", "pr", "head", "request"]
    if not all(k in status for k in required_keys):
        print("STOP_AND_WAIT: Malformed status.json missing required fields.")
        return

    canonical_repo = get_canonical_repo(profile)

    if status["repo"] != canonical_repo:
        print(f"STOP_AND_WAIT: Unknown repository {status['repo']}")
        return

    state = status["state"]
    if state in ["REVIEW_REQUESTED", "REVIEW_REQUESTED_AGAIN"]:
        req_id = str(uuid.uuid4())
        status["request_id"] = req_id
        status["state"] = "WAITING_FOR_REVIEW"
        save_status(status)

        payload = (
            f"REVIEW_REQUEST_ID: {req_id}\n"
            f"REPO: {status['repo']}\n"
            f"PR: {status['pr']}\n"
            f"HEAD: {status['head']}\n"
            f"REQUEST: {status['request']}\n"
        )
        
        with open(get_request_file(), "w") as f:
            f.write(payload)
            
        print("REVIEW_REQUEST")
        print(f"Request file created at: {get_request_file()}")
    else:
        print(f"No outgoing request. Current state: {state}")

def execute_stop_protocol(profile, summary, unauthorized_actions):
    status = load_status()
    if not status:
        print("No status.json found.")
        sys.exit(1)

    stop_states = {"WAITING_PO_AUTH", "BLOCKED", "CHANGES_REQUESTED", "NEEDS_OWNER_DECISION", "DONE"}
    if status.get("state") not in stop_states:
        print(f"STOP_AND_WAIT: Cannot execute stop protocol from non-stop state: {status.get('state')}")
        sys.exit(1)

    pr = status.get('pr')
    if not pr:
        print("STOP_AND_WAIT: Missing PR in status.json.")
        sys.exit(1)

    # 1. Authoritative remote read-back
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr), "--json", "headRefOid"],
            capture_output=True, text=True, check=True
        )
        remote_pr_data = json.loads(result.stdout)
        remote_head = remote_pr_data.get("headRefOid")
    except Exception as e:
        # In test environments or on failure, fail closed
        print(f"STOP_AND_WAIT: Failed to read remote PR via gh cli: {e}")
        sys.exit(1)

    if remote_head != status.get('head'):
        print(f"STOP_AND_WAIT: Remote HEAD mismatch. Local: {status.get('head')}, Remote: {remote_head}")
        sys.exit(1)

    # 2. Check idempotency
    episode = status.get("stop_episode")
    if episode:
        if episode.get("state") == status.get("state") and episode.get("head") == status.get("head") and episode.get("pr") == pr:
            if episode.get("acked"):
                print("STOP_AND_WAIT: Status report already successfully sent and ACKed for this exact state and HEAD.")
                sys.exit(0)
            else:
                print("Warning: Previous status report was not ACKed. Re-sending.")
        else:
            # Different state/head/pr, new episode
            episode = None

    # 3. Create Status Report
    canonical_repo = get_canonical_repo(profile)
    repo = status.get('repo')
    
    if not repo or repo != canonical_repo:
        print("STOP_AND_WAIT: Missing or invalid REPO in status.json for status_report.")
        sys.exit(1)

    if not episode:
        req_id = str(uuid.uuid4())
        status["stop_episode"] = {
            "request_id": req_id,
            "state": status.get("state"),
            "head": status.get("head"),
            "pr": pr,
            "acked": False
        }
    else:
        req_id = episode["request_id"]

    save_status(status)

    payload = (
        f"REVIEW_REQUEST_ID: {req_id}\n"
        f"REPO: {repo}\n"
        f"PR: {pr}\n"
        f"HEAD: {remote_head}\n"
        f"REQUEST: status_report\n"
        f"STATE: {status.get('state')}\n"
        f"SUMMARY: {summary}\n"
        f"UNAUTHORIZED_ACTIONS: {unauthorized_actions}\n"
    )
    
    with open(get_request_file(), "w") as f:
        f.write(payload)
        
    print("STATUS_REPORT created.")
    
    # 4. Loop neutral relay until ACK
    print("Sending via neutral relay...")
    rf = get_review_file()
    max_retries = 30
    for _ in range(max_retries):
        if os.path.exists(rf):
            os.remove(rf)
        relay_cmd = ["python3", os.path.expanduser("~/.agentops/relay/neutral_relay.py"), 
                     "--request-file", get_request_file(), 
                     "--output-file", rf]
        subprocess.run(relay_cmd)
        
        # Check if file has ACK line
        if os.path.exists(rf):
            with open(rf, "r") as f:
                content = f.read()
                if "ACK: status_report_received" in content:
                    print("Received ACK.")
                    process_ack(profile, current_head=remote_head)
                    return
        print("No valid ACK received. Retrying in 5 seconds...")
        time.sleep(5)
    
    print("STOP_AND_WAIT: Failed to get valid ACK after retries.")
    sys.exit(1)


def handle_gpt_review_return(profile, current_head=None):
    if not current_head:
        print("STOP_AND_WAIT: Missing --current-head argument. Cannot verify stale reviews without remote PR HEAD.")
        return

    status = load_status()
    if not status:
        print("No status.json found.")
        return

    rf = get_review_file()
    if not os.path.exists(rf):
        print("No gpt-review.md found.")
        return

    if status["state"] != "WAITING_FOR_REVIEW":
        print(f"Not waiting for review. Current state: {status['state']}")
        return

    with open(rf, "r") as f:
        content = f.read()

    lines = content.split('\n')
    verdict = None
    pr = None
    head = None
    req_id = None
    review_repo = None

    for line in lines:
        if line.startswith("VERDICT:"):
            verdict = line.split("VERDICT:")[1].strip()
        elif line.startswith("PR:"):
            pr = line.split("PR:")[1].strip()
        elif line.startswith("HEAD:"):
            head = line.split("HEAD:")[1].strip()
        elif line.startswith("REVIEW_REQUEST_ID:"):
            req_id = line.split("REVIEW_REQUEST_ID:")[1].strip()
        elif line.startswith("REPO:"):
            review_repo = line.split("REPO:")[1].strip()

    if status.get("request_id") and req_id != status.get("request_id"):
        print(f"STOP_AND_WAIT: Stale review detected (request_id mismatch). Expected {status.get('request_id')} got {req_id}")
        return

    canonical_repo = get_canonical_repo(profile)

    if review_repo != status.get("repo") or review_repo != canonical_repo:
        print(f"STOP_AND_WAIT: REPO mismatch. Review REPO ({review_repo}) vs Status ({status.get('repo')}) vs Canonical ({canonical_repo}).")
        return

    status_head = status["head"]
    
    if head != status_head or head != current_head:
        print(f"STOP_AND_WAIT: Stale review detected. Review HEAD ({head}) vs Status HEAD ({status_head}) vs Current HEAD ({current_head}).")
        return

    if str(pr) != str(status["pr"]):
        print("STOP_AND_WAIT: PR mismatch in review.")
        return

    if verdict == "PASS":
        status["state"] = "WAITING_PO_AUTH"
    elif verdict == "CHANGES_REQUESTED":
        status["state"] = "CHANGES_REQUESTED"
    elif verdict in ["BLOCKED", "NEEDS_OWNER_DECISION"]:
        status["state"] = "BLOCKED"
    else:
        print(f"STOP_AND_WAIT: Unknown verdict {verdict}")
        return

    # Clear stop episode if state transitions
    status.pop("stop_episode", None)
    save_status(status)
    print(f"Review processed successfully. New state: {status['state']}")
    
    stop_states = {"WAITING_PO_AUTH", "BLOCKED", "CHANGES_REQUESTED", "NEEDS_OWNER_DECISION", "DONE"}
    if status["state"] in stop_states:
        # Automate the stop protocol reporting
        execute_stop_protocol(profile, summary=f"Entered stop state {status['state']}", unauthorized_actions="NONE")

def process_ack(profile, current_head=None):
    if not current_head:
        print("STOP_AND_WAIT: Missing --current-head argument.")
        return

    status = load_status()
    if not status:
        print("No status.json found.")
        return

    rf = get_review_file()
    if not os.path.exists(rf):
        print("No gpt-review.md found.")
        return

    with open(rf, "r") as f:
        content = f.read()

    lines = content.split('\n')
    ack = None
    pr = None
    head = None
    req_id = None
    review_repo = None

    for line in lines:
        if line.startswith("ACK:"):
            ack = line.split("ACK:")[1].strip()
        elif line.startswith("PR:"):
            pr = line.split("PR:")[1].strip()
        elif line.startswith("HEAD:"):
            head = line.split("HEAD:")[1].strip()
        elif line.startswith("REVIEW_REQUEST_ID:") or line.startswith("REPORT_ID:"):
            req_id = line.split(":", 1)[1].strip()
        elif line.startswith("REPO:"):
            review_repo = line.split("REPO:")[1].strip()

    episode = status.get("stop_episode")
    if not episode:
        print("STOP_AND_WAIT: No active stop episode found.")
        return

    if not req_id or req_id != episode.get("request_id"):
        print(f"STOP_AND_WAIT: Mismatched ACK ID. Expected {episode.get('request_id')} got {req_id}")
        return

    canonical_repo = get_canonical_repo(profile)

    if review_repo != status.get("repo") or review_repo != canonical_repo:
        print("STOP_AND_WAIT: REPO mismatch in ACK.")
        return

    if head != status.get("head") or head != current_head:
        print("STOP_AND_WAIT: HEAD mismatch in ACK.")
        return

    if str(pr) != str(status.get("pr")):
        print("STOP_AND_WAIT: PR mismatch in ACK.")
        return

    if ack != "status_report_received":
        print(f"STOP_AND_WAIT: Invalid ACK received: {ack}")
        return

    # Success, record ACK in episode
    episode["acked"] = True
    save_status(status)
    print(f"ACK verified successfully. State remains: {status['state']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", help="Command to run", default="request_review")
    parser.add_argument("--current-head", help="Current remote PR HEAD SHA to prevent stale reviews.")
    parser.add_argument("--summary", help="Summary for status report")
    parser.add_argument("--unauthorized-actions", help="Unauthorized actions for status report", default="NONE")
    parser.add_argument("--profile", help="Path to project profile JSON", default=DEFAULT_PROFILE)
    args = parser.parse_args()

    profile = load_profile(args.profile)
    
    if args.command == "process_review":
        if not args.current_head:
            print("STOP_AND_WAIT: Missing --current-head argument.")
            sys.exit(1)
        handle_gpt_review_return(profile, current_head=args.current_head)
    elif args.command == "execute_stop_protocol":
        execute_stop_protocol(profile, summary=args.summary or "Status update.", unauthorized_actions=args.unauthorized_actions)
    elif args.command == "process_ack":
        if not args.current_head:
            print("STOP_AND_WAIT: Missing --current-head argument.")
            sys.exit(1)
        process_ack(profile, current_head=args.current_head)
    elif args.command == "request_review":
        handle_review_request(profile)
    else:
        print(f"Unknown command: {args.command}")
