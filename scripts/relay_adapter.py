import json
import os
import sys
import argparse
import uuid

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
# Removed PASS from allowed states as PASS is just a verdict, not a durable state.
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

    # 4. malformed state
    required_keys = ["protocol_version", "state", "repo", "pr", "head", "request"]
    if not all(k in status for k in required_keys):
        print("STOP_AND_WAIT: Malformed status.json missing required fields.")
        return

    canonical_repo = get_canonical_repo(profile)

    # 5. wrong repository
    if status["repo"] != canonical_repo:
        print(f"STOP_AND_WAIT: Unknown repository {status['repo']}")
        return

    state = status["state"]
    if state in ["REVIEW_REQUESTED", "REVIEW_REQUESTED_AGAIN"]:
        # generate unique request_id
        req_id = str(uuid.uuid4())
        status["request_id"] = req_id
        # State transition to WAITING_FOR_REVIEW immediately so it doesn't trigger twice
        status["state"] = "WAITING_FOR_REVIEW"
        save_status(status)

        # Output payload for Neutral Relay
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

    # Minimal parsing
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

    # Verify REPO binding
    if review_repo != status.get("repo") or review_repo != canonical_repo:
        print(f"STOP_AND_WAIT: REPO mismatch. Review REPO ({review_repo}) vs Status ({status.get('repo')}) vs Canonical ({canonical_repo}).")
        return

    # 1. stale review (Triple HEAD binding)
    status_head = status["head"]
    
    if head != status_head or head != current_head:
        print(f"STOP_AND_WAIT: Stale review detected. Review HEAD ({head}) vs Status HEAD ({status_head}) vs Current HEAD ({current_head}).")
        # Do NOT accept PASS, Do NOT transition to WAITING_PO_AUTH. We stay in WAITING_FOR_REVIEW or request again.
        return

    if str(pr) != str(status["pr"]):
        print("STOP_AND_WAIT: PR mismatch in review.")
        return

    if verdict == "PASS":
        # 6. PASS ≠ Merge Authorization
        status["state"] = "WAITING_PO_AUTH"
    elif verdict == "CHANGES_REQUESTED":
        status["state"] = "CHANGES_REQUESTED"
    elif verdict in ["BLOCKED", "NEEDS_OWNER_DECISION"]:
        status["state"] = "BLOCKED"
    else:
        print(f"STOP_AND_WAIT: Unknown verdict {verdict}")
        return

    status.pop("status_report_acked", None)
    save_status(status)
    print(f"Review processed successfully. New state: {status['state']}")

def handle_status_report(profile, summary, unauthorized_actions):
    status = load_status()
    if not status:
        print("No status.json found.")
        return

    # P0: Enforce stop states
    stop_states = {"WAITING_PO_AUTH", "BLOCKED", "CHANGES_REQUESTED", "NEEDS_OWNER_DECISION", "DONE"}
    if status.get("state") not in stop_states:
        print(f"STOP_AND_WAIT: Cannot send status_report from non-stop state: {status.get('state')}")
        return

    if status.get("status_report_acked"):
        print("STOP_AND_WAIT: Status report already acknowledged for this state.")
        return

    canonical_repo = get_canonical_repo(profile)

    # P1: Strict envelope binding
    repo = status.get('repo')
    pr = status.get('pr')
    head = status.get('head')
    
    if not repo or not pr or not head or repo != canonical_repo:
        print("STOP_AND_WAIT: Missing or invalid REPO/PR/HEAD in status.json for status_report.")
        return

    req_id = str(uuid.uuid4())
    # Save the request_id to verify the ACK later
    status["request_id"] = req_id
    save_status(status)

    payload = (
        f"REVIEW_REQUEST_ID: {req_id}\n"
        f"REPO: {repo}\n"
        f"PR: {pr}\n"
        f"HEAD: {head}\n"
        f"REQUEST: status_report\n"
        f"STATE: {status.get('state')}\n"
        f"SUMMARY: {summary}\n"
        f"UNAUTHORIZED_ACTIONS: {unauthorized_actions}\n"
    )
    
    with open(get_request_file(), "w") as f:
        f.write(payload)
        
    print("STATUS_REPORT")
    print(f"Request file created at: {get_request_file()}")

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

    if not req_id or req_id != status.get("request_id"):
        print(f"STOP_AND_WAIT: Mismatched ACK ID. Expected {status.get('request_id')} got {req_id}")
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

    # Success, state is unchanged
    status["status_report_acked"] = True
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
    elif args.command == "status_report":
        handle_status_report(profile, summary=args.summary or "Status update.", unauthorized_actions=args.unauthorized_actions)
    elif args.command == "process_ack":
        if not args.current_head:
            print("STOP_AND_WAIT: Missing --current-head argument.")
            sys.exit(1)
        process_ack(profile, current_head=args.current_head)
    elif args.command == "request_review":
        handle_review_request(profile)
    else:
        print(f"Unknown command: {args.command}")
