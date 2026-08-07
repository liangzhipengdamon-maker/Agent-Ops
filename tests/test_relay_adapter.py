import unittest
import json
import os
import sys

# Ensure scripts can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
from relay_adapter import handle_review_request, handle_gpt_review_return, BRIDGE_DIR, STATUS_FILE, REVIEW_FILE

class TestRelayAdapter(unittest.TestCase):
    def setUp(self):
        os.makedirs(BRIDGE_DIR, exist_ok=True)
        self.initial_status = {
            "protocol_version": "1",
            "state": "REVIEW_REQUESTED",
            "repo": "liangzhipengdamon-maker/Agent-Ops",
            "pr": 5,
            "head": "abcdef123456",
            "request": "independent_review"
        }
        with open(STATUS_FILE, "w") as f:
            json.dump(self.initial_status, f)
            
        if os.path.exists(REVIEW_FILE):
            os.remove(REVIEW_FILE)

    def tearDown(self):
        # Reset status.json to IDLE state for safety instead of deleting
        idle_status = {
            "protocol_version": "1",
            "state": "IDLE",
            "repo": "liangzhipengdamon-maker/Agent-Ops",
            "pr": None,
            "head": None,
            "request": None
        }
        with open(STATUS_FILE, "w") as f:
            json.dump(idle_status, f, indent=2)
            
        if os.path.exists(REVIEW_FILE):
            os.remove(REVIEW_FILE)

    def test_review_request_transitions_to_waiting(self):
        handle_review_request()
        with open(STATUS_FILE, "r") as f:
            status = json.load(f)
        self.assertEqual(status["state"], "WAITING_FOR_REVIEW")

    def test_gpt_review_pass(self):
        # 1. Trigger request
        handle_review_request()
        
        # 2. Mock GPT Review
        with open(REVIEW_FILE, "w") as f:
            f.write("VERDICT: PASS\nPR: 5\nHEAD: abcdef123456\nSUMMARY:\nLooks good.\nACTIONS:\n")
            
        # 3. Process return
        handle_gpt_review_return()
        
        with open(STATUS_FILE, "r") as f:
            status = json.load(f)
        self.assertEqual(status["state"], "WAITING_PO_AUTH") # 6. PASS ≠ Merge Authorization

    def test_gpt_review_changes_requested(self):
        handle_review_request()
        with open(REVIEW_FILE, "w") as f:
            f.write("VERDICT: CHANGES_REQUESTED\nPR: 5\nHEAD: abcdef123456\n")
        handle_gpt_review_return()
        with open(STATUS_FILE, "r") as f:
            status = json.load(f)
        self.assertEqual(status["state"], "CHANGES_REQUESTED")

    def test_stale_review_rejected(self):
        handle_review_request()
        with open(REVIEW_FILE, "w") as f:
            f.write("VERDICT: PASS\nPR: 5\nHEAD: 000000000000\n")
        
        handle_gpt_review_return()
        
        with open(STATUS_FILE, "r") as f:
            status = json.load(f)
        # Should remain WAITING_FOR_REVIEW because the review was rejected as stale
        self.assertEqual(status["state"], "WAITING_FOR_REVIEW")

if __name__ == '__main__':
    unittest.main()
