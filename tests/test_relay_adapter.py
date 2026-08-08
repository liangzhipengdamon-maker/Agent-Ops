import unittest
import unittest.mock
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
            "project_identity": "test",
            "github": {
                "repository": "liangzhipengdamon-maker/Agent-Ops",
                "canonical_branch": "main"
            },
            "linear": {"team_key": "TEST", "project_id": "test-id"},
            "local_builder": {"relative_path": ".", "required_env_vars": []},
            "validation": {"ci_command": "true"},
            "reviewer_relay": {"binding_type": "test", "contact_uri": "test://uri"},
            "governance": {
                "capabilities": ["independent_review"],
                "required_gates": ["WAITING_PO_AUTH"],
                "protected_project": False,
                "cross_project_allowed": False
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

    @unittest.mock.patch('relay_adapter.execute_stop_protocol')
    def test_gpt_review_triple_head_match_pass(self, mock_exec):
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

    @unittest.mock.patch('relay_adapter.execute_stop_protocol')
    def test_alternate_project_positive_path(self, mock_exec):
        # Create an alternate profile
        alt_profile = {
            "project_identity": "test-alt",
            "github": {
                "repository": "example-org/example-repo",
                "canonical_branch": "main"
            },
            "linear": {"team_key": "TEST", "project_id": "test-id"},
            "validation": {"ci_command": "true"},
            "reviewer_relay": {"binding_type": "test", "contact_uri": "test://uri"},
            "governance": {
                "capabilities": ["independent_review"],
                "required_gates": ["WAITING_PO_AUTH"],
                "protected_project": False,
                "cross_project_allowed": False
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
            "project_identity": "test-alt",
            "github": {
                "repository": "example-org/example-repo",
                "canonical_branch": "main"
            },
            "linear": {"team_key": "TEST", "project_id": "test-id"},
            "validation": {"ci_command": "true"},
            "reviewer_relay": {"binding_type": "test", "contact_uri": "test://uri"},
            "governance": {
                "capabilities": ["independent_review"],
                "required_gates": ["WAITING_PO_AUTH"],
                "protected_project": False,
                "cross_project_allowed": False
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

class TestRelayAdapterLoadProfile(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.valid_profile = {
            "project_identity": "test",
            "github": {"repository": "test/repo", "canonical_branch": "main"},
            "linear": {"team_key": "TEST", "project_id": "test-id"},
            "local_builder": {"relative_path": ".", "required_env_vars": []},
            "validation": {"ci_command": "true"},
            "reviewer_relay": {"binding_type": "test", "contact_uri": "test://uri"},
            "governance": {
                "capabilities": ["independent_review"],
                "required_gates": ["WAITING_PO_AUTH"],
                "protected_project": False,
                "cross_project_allowed": False
            }
        }
        self.profile_path = os.path.join(self.temp_dir.name, "profile.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_profile_load_success(self):
        with open(self.profile_path, "w") as f:
            json.dump(self.valid_profile, f)
        # Should return successfully
        profile = relay_adapter.load_profile(self.profile_path)
        self.assertEqual(profile["project_identity"], "test")

    def test_unknown_field_fail_closed(self):
        invalid_profile = dict(self.valid_profile)
        invalid_profile["unknown_field"] = "bad"
        with open(self.profile_path, "w") as f:
            json.dump(invalid_profile, f)
        with self.assertRaises(SystemExit) as cm:
            relay_adapter.load_profile(self.profile_path)
        self.assertEqual(cm.exception.code, 1)

    def test_missing_required_field_fail_closed(self):
        invalid_profile = dict(self.valid_profile)
        del invalid_profile["github"]
        with open(self.profile_path, "w") as f:
            json.dump(invalid_profile, f)
        with self.assertRaises(SystemExit) as cm:
            relay_adapter.load_profile(self.profile_path)
        self.assertEqual(cm.exception.code, 1)

    def test_malformed_profile_json_fail_closed(self):
        with open(self.profile_path, "w") as f:
            f.write("{ bad json ")
        with self.assertRaises(SystemExit) as cm:
            relay_adapter.load_profile(self.profile_path)
        self.assertEqual(cm.exception.code, 1)

    @unittest.mock.patch('relay_adapter.__file__', new='/tmp/fake_dir/fake.py')
    def test_missing_schema_fail_closed(self):
        with open(self.profile_path, "w") as f:
            json.dump(self.valid_profile, f)
        with self.assertRaises(SystemExit) as cm:
            relay_adapter.load_profile(self.profile_path)
        self.assertEqual(cm.exception.code, 1)

    @unittest.mock.patch('relay_adapter.__file__', new='/tmp/fake_dir/fake.py')
    def test_malformed_schema_fail_closed(self):
        # Create a fake schema that is malformed
        fake_schema_dir = "/tmp/docs/schemas"
        os.makedirs(fake_schema_dir, exist_ok=True)
        fake_schema_path = os.path.join(fake_schema_dir, "project_profile.schema.json")
        with open(fake_schema_path, "w") as f:
            f.write("{ malformed schema ")
            
        with open(self.profile_path, "w") as f:
            json.dump(self.valid_profile, f)
            
        try:
            with self.assertRaises(SystemExit) as cm:
                relay_adapter.load_profile(self.profile_path)
            self.assertEqual(cm.exception.code, 1)
        finally:
            if os.path.exists(fake_schema_path):
                os.remove(fake_schema_path)

if __name__ == '__main__':
    unittest.main()
