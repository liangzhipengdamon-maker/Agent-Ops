import json
import os
import sys
import argparse

def get_bridge_dir():
    return os.environ.get("AGENT_BRIDGE_DIR", ".agent-bridge")

def get_status_file():
    return os.path.join(get_bridge_dir(), "status.json")

def get_review_file():
    return os.path.join(get_bridge_dir(), "gpt-review.md")

CANONICAL_REPO = "liangzhipengdamon-maker/Agent-Ops"

# Removed PASS from allowed states as PASS is just a verdict, not a durable state.
ALLOWED_STATES = {
    "IDLE",
    "REVIEW_REQUESTED",
    "WAITING_FOR_REVIEW",
    "CHANGES_REQUESTED",
    "BUILDER_FIXING",
    "REVIEW_REQUESTED_AGAIN",
    "BLOCKED",
    "WAITING_PO_AUTH"
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

def handle_review_request():
    status = load_status()
    if not status:
        print("No status.json found.")
        return

    # 4. malformed state
    required_keys = ["protocol_version", "state", "repo", "pr", "head", "request"]
    if not all(k in status for k in required_keys):
        print("STOP_AND_WAIT: Malformed status.json missing required fields.")
        return

    # 5. wrong repository
    if status["repo"] != CANONICAL_REPO:
        print(f"STOP_AND_WAIT: Unknown repository {status['repo']}")
        return

    state = status["state"]
    if state in ["REVIEW_REQUESTED", "REVIEW_REQUESTED_AGAIN"]:
        # 2. duplicate request / infinite loop prevention
        # State transition to WAITING_FOR_REVIEW immediately so it doesn't trigger twice
        status["state"] = "WAITING_FOR_REVIEW"
        save_status(status)

        # Output minimal payload for GPT as per rules (Relay boundary)
        print("REVIEW_REQUEST")
        print(f"repo: {status['repo']}")
        print(f"pr: {status['pr']}")
        print(f"head: {status['head']}")
    else:
        print(f"No outgoing request. Current state: {state}")

def handle_gpt_review_return(current_head=None):
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

    for line in lines:
        if line.startswith("VERDICT:"):
            verdict = line.split("VERDICT:")[1].strip()
        elif line.startswith("PR:"):
            pr = line.split("PR:")[1].strip()
        elif line.startswith("HEAD:"):
            head = line.split("HEAD:")[1].strip()

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

    save_status(status)
    print(f"Review processed successfully. New state: {status['state']}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "process_review":
        parser = argparse.ArgumentParser()
        parser.add_argument("command", help="Command to run")
        parser.add_argument("--current-head", required=True, help="Current remote PR HEAD SHA to prevent stale reviews.")
        args = parser.parse_args()
        handle_gpt_review_return(current_head=args.current_head)
    else:
        handle_review_request()
