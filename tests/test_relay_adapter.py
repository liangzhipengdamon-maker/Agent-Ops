import unittest
import json
import os
import sys
import tempfile

# Ensure scripts can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
import relay_adapter

class TestRelayAdapter(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory to strictly isolate tests from real .agent-bridge
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["AGENT_BRIDGE_DIR"] = self.temp_dir.name
        
        self.status_file = relay_adapter.get_status_file()
        self.review_file = relay_adapter.get_review_file()
        
        self.mock_profile = {
            "github": {
                "repository": "liangzhipengdamon-maker/Agent-Ops"
            }
        }
        
        # We don't touch the real bridge directory at all.
        self.initial_status = {
            "protocol_version": "1",
            "state": "REVIEW_REQUESTED",
            "repo": "liangzhipengdamon-maker/Agent-Ops",
            "pr": 5,
            "head": "abcdef123456",
            "request": "independent_review"
        }
        with open(self.status_file, "w") as f:
            json.dump(self.initial_status, f)

    def tearDown(self):
        # Clean up isolated temp directory
        self.temp_dir.cleanup()
        if "AGENT_BRIDGE_DIR" in os.environ:
            del os.environ["AGENT_BRIDGE_DIR"]

    def test_review_request_transitions_to_waiting(self):
        relay_adapter.handle_review_request(self.mock_profile)
        with open(self.status_file, "r") as f:
            status = json.load(f)
        self.assertEqual(status["state"], "WAITING_FOR_REVIEW")

    def test_gpt_review_triple_head_match_pass(self):
        relay_adapter.handle_review_request(self.mock_profile)
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        req_id = status["request_id"]
        
        with open(self.review_file, "w") as f:
            f.write(f"REVIEW_REQUEST_ID: {req_id}\nVERDICT: PASS\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 5\nHEAD: abcdef123456\nSUMMARY:\nLooks good.\nACTIONS:\n")
            
        # Provide matching current_head
        relay_adapter.handle_gpt_review_return(self.mock_profile, current_head="abcdef123456")
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        self.assertEqual(status["state"], "WAITING_PO_AUTH")

    def test_gpt_review_missing_current_head_fails_closed(self):
        relay_adapter.handle_review_request(self.mock_profile)
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        req_id = status["request_id"]
        
        with open(self.review_file, "w") as f:
            f.write(f"REVIEW_REQUEST_ID: {req_id}\nVERDICT: PASS\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 5\nHEAD: abcdef123456\n")
            
        # Provide NO current_head
        relay_adapter.handle_gpt_review_return(self.mock_profile, current_head=None)
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        # Rejects review, does not transition
        self.assertEqual(status["state"], "WAITING_FOR_REVIEW")

    def test_stale_review_rejected_review_head_mismatch(self):
        relay_adapter.handle_review_request(self.mock_profile)
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        req_id = status["request_id"]
        
        with open(self.review_file, "w") as f:
            f.write(f"REVIEW_REQUEST_ID: {req_id}\nVERDICT: PASS\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 5\nHEAD: 000000000000\n")
        
        relay_adapter.handle_gpt_review_return(self.mock_profile, current_head="abcdef123456")
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        self.assertEqual(status["state"], "WAITING_FOR_REVIEW")

    def test_stale_review_rejected_current_head_mismatch(self):
        relay_adapter.handle_review_request(self.mock_profile)
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        req_id = status["request_id"]
        
        with open(self.review_file, "w") as f:
            f.write(f"REVIEW_REQUEST_ID: {req_id}\nVERDICT: PASS\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 5\nHEAD: abcdef123456\n")
        
        # The remote GitHub PR HEAD drifted!
        relay_adapter.handle_gpt_review_return(self.mock_profile, current_head="drifted12345")
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        # Should stay WAITING_FOR_REVIEW, effectively rejecting the stale PASS verdict
        self.assertEqual(status["state"], "WAITING_FOR_REVIEW")

    def test_missing_repo_fails_closed(self):
        relay_adapter.handle_review_request(self.mock_profile)
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        req_id = status["request_id"]
        
        with open(self.review_file, "w") as f:
            # MISSING REPO
            f.write(f"REVIEW_REQUEST_ID: {req_id}\nVERDICT: PASS\nPR: 5\nHEAD: abcdef123456\n")
        
        relay_adapter.handle_gpt_review_return(self.mock_profile, current_head="abcdef123456")
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        self.assertEqual(status["state"], "WAITING_FOR_REVIEW")

    def test_mismatched_repo_fails_closed(self):
        relay_adapter.handle_review_request(self.mock_profile)
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        req_id = status["request_id"]
        
        with open(self.review_file, "w") as f:
            # MISMATCHED REPO
            f.write(f"REVIEW_REQUEST_ID: {req_id}\nVERDICT: PASS\nREPO: some/other-repo\nPR: 5\nHEAD: abcdef123456\n")
        
        relay_adapter.handle_gpt_review_return(self.mock_profile, current_head="abcdef123456")
        
        with open(self.status_file, "r") as f:
            status = json.load(f)
        self.assertEqual(status["state"], "WAITING_FOR_REVIEW")

    def test_handle_status_report_success(self):
        status = {
            "protocol_version": "1.0",
            "state": "WAITING_PO_AUTH",
            "repo": "liangzhipengdamon-maker/Agent-Ops",
            "pr": 42,
            "head": "abcdef123456",
            "request": "Independent review for PR"
        }
        with open(os.path.join(self.temp_dir.name, "status.json"), "w") as f:
            json.dump(status, f)

        relay_adapter.handle_status_report(self.mock_profile, "Test summary", "NONE")
        
        request_file = os.path.join(self.temp_dir.name, "request.txt")
        self.assertTrue(os.path.exists(request_file))
        
        with open(request_file, "r") as f:
            content = f.read()
            
        self.assertIn("REVIEW_REQUEST_ID:", content)
        self.assertIn("REPO: liangzhipengdamon-maker/Agent-Ops", content)
        self.assertIn("PR: 42", content)
        self.assertIn("HEAD: abcdef123456", content)
        self.assertIn("REQUEST: status_report", content)
        self.assertIn("STATE: WAITING_PO_AUTH", content)
        self.assertIn("SUMMARY: Test summary", content)
        self.assertIn("UNAUTHORIZED_ACTIONS: NONE", content)
        
        with open(os.path.join(self.temp_dir.name, "status.json"), "r") as f:
            updated_status = json.load(f)
        self.assertIn("request_id", updated_status)

    def test_handle_status_report_non_stop_state(self):
        status = {
            "protocol_version": "1.0",
            "state": "REVIEW_REQUESTED",
            "repo": "liangzhipengdamon-maker/Agent-Ops",
            "pr": 42,
            "head": "abcdef123456"
        }
        with open(os.path.join(self.temp_dir.name, "status.json"), "w") as f:
            json.dump(status, f)

        relay_adapter.handle_status_report(self.mock_profile, "Test summary", "NONE")
        request_file = os.path.join(self.temp_dir.name, "request.txt")
        self.assertFalse(os.path.exists(request_file))

    def test_handle_status_report_missing_envelope(self):
        status = {
            "protocol_version": "1.0",
            "state": "WAITING_PO_AUTH",
            "repo": "liangzhipengdamon-maker/Agent-Ops",
            "head": "abcdef123456"
            # Missing pr
        }
        with open(os.path.join(self.temp_dir.name, "status.json"), "w") as f:
            json.dump(status, f)

        relay_adapter.handle_status_report(self.mock_profile, "Test summary", "NONE")
        request_file = os.path.join(self.temp_dir.name, "request.txt")
        self.assertFalse(os.path.exists(request_file))

    def test_process_ack_success(self):
        status = {
            "protocol_version": "1.0",
            "state": "WAITING_PO_AUTH",
            "repo": "liangzhipengdamon-maker/Agent-Ops",
            "pr": 42,
            "head": "abcdef123456",
            "request_id": "test-req-123"
        }
        with open(os.path.join(self.temp_dir.name, "status.json"), "w") as f:
            json.dump(status, f)

        review = (
            "REVIEW_REQUEST_ID: test-req-123\n"
            "REPO: liangzhipengdamon-maker/Agent-Ops\n"
            "PR: 42\n"
            "HEAD: abcdef123456\n"
            "ACK: status_report_received\n"
        )
        with open(os.path.join(self.temp_dir.name, "gpt-review.md"), "w") as f:
            f.write(review)

        relay_adapter.process_ack(self.mock_profile, current_head="abcdef123456")
        
        with open(os.path.join(self.temp_dir.name, "status.json"), "r") as f:
            updated = json.load(f)
        self.assertEqual(updated["state"], "WAITING_PO_AUTH")

    def test_process_ack_mismatched_id(self):
        status = {
            "protocol_version": "1.0",
            "state": "WAITING_PO_AUTH",
            "repo": "liangzhipengdamon-maker/Agent-Ops",
            "pr": 42,
            "head": "abcdef123456",
            "request_id": "test-req-123"
        }
        with open(os.path.join(self.temp_dir.name, "status.json"), "w") as f:
            json.dump(status, f)

        review = (
            "REVIEW_REQUEST_ID: mismatched-id\n"
            "REPO: liangzhipengdamon-maker/Agent-Ops\n"
            "PR: 42\n"
            "HEAD: abcdef123456\n"
            "ACK: status_report_received\n"
        )
        with open(os.path.join(self.temp_dir.name, "gpt-review.md"), "w") as f:
            f.write(review)

        # Output should be STOP_AND_WAIT
        relay_adapter.process_ack(self.mock_profile, current_head="abcdef123456")

    def test_alternate_project_positive_path(self):
        # Create an alternate profile
        alt_profile = {
            "github": {
                "repository": "example-org/example-repo"
            }
        }
        
        # Set status.json to match alternate profile
        status = {
            "protocol_version": "1.0",
            "state": "REVIEW_REQUESTED",
            "repo": "example-org/example-repo",
            "pr": 99,
            "head": "alt123456",
            "request": "review alternate"
        }
        with open(os.path.join(self.temp_dir.name, "status.json"), "w") as f:
            json.dump(status, f)
            
        relay_adapter.handle_review_request(alt_profile)
        
        with open(os.path.join(self.temp_dir.name, "status.json"), "r") as f:
            status = json.load(f)
        self.assertEqual(status["state"], "WAITING_FOR_REVIEW")
        
        req_id = status["request_id"]
        
        # Write matching review
        with open(self.review_file, "w") as f:
            f.write(f"REVIEW_REQUEST_ID: {req_id}\nVERDICT: PASS\nREPO: example-org/example-repo\nPR: 99\nHEAD: alt123456\nSUMMARY:\nLooks good.\nACTIONS:\n")
            
        relay_adapter.handle_gpt_review_return(alt_profile, current_head="alt123456")
        
        with open(os.path.join(self.temp_dir.name, "status.json"), "r") as f:
            final_status = json.load(f)
        self.assertEqual(final_status["state"], "WAITING_PO_AUTH")

    def test_repository_mismatch_fail_closed(self):
        alt_profile = {
            "github": {
                "repository": "example-org/example-repo"
            }
        }
        
        # Status has wrong repo (not matching profile)
        status = {
            "protocol_version": "1.0",
            "state": "REVIEW_REQUESTED",
            "repo": "malicious-org/wrong-repo",
            "pr": 99,
            "head": "alt123456",
            "request": "review alternate"
        }
        with open(os.path.join(self.temp_dir.name, "status.json"), "w") as f:
            json.dump(status, f)
            
        relay_adapter.handle_review_request(alt_profile)
        
        with open(os.path.join(self.temp_dir.name, "status.json"), "r") as f:
            status = json.load(f)
        # Should be rejected, state should remain REVIEW_REQUESTED
        self.assertEqual(status["state"], "REVIEW_REQUESTED")
        
        # Manually force into WAITING_FOR_REVIEW to test the return path
        status["state"] = "WAITING_FOR_REVIEW"
        status["request_id"] = "test-req-123"
        with open(os.path.join(self.temp_dir.name, "status.json"), "w") as f:
            json.dump(status, f)
            
        # Review has matching wrong repo, but profile is different
        with open(self.review_file, "w") as f:
            f.write(f"REVIEW_REQUEST_ID: test-req-123\nVERDICT: PASS\nREPO: malicious-org/wrong-repo\nPR: 99\nHEAD: alt123456\nSUMMARY:\nLooks good.\nACTIONS:\n")
            
        relay_adapter.handle_gpt_review_return(alt_profile, current_head="alt123456")
        
        with open(os.path.join(self.temp_dir.name, "status.json"), "r") as f:
            final_status = json.load(f)
        # Should fail closed and not transition to WAITING_PO_AUTH
        self.assertEqual(final_status["state"], "WAITING_FOR_REVIEW")

if __name__ == '__main__':
    unittest.main()
