import unittest
import unittest.mock
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
import relay_adapter

class TestRelayAdapter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["AGENT_BRIDGE_DIR"] = self.temp_dir.name
        self.status_file = relay_adapter.get_status_file()
        self.review_file = relay_adapter.get_review_file()
        self.mock_profile = {
            "project_identity": "test",
            "github": {"repository": "liangzhipengdamon-maker/Agent-Ops", "canonical_branch": "main"},
            "linear": {"team_key": "TEST", "project_id": "test-id"},
            "local_builder": {"relative_path": ".", "required_env_vars": []},
            "validation": {"ci_command": "true"},
            "reviewer_relay": {"binding_type": "test", "contact_uri": "test://uri"},
            "governance": {"capabilities": ["independent_review"], "required_gates": ["WAITING_PO_AUTH"], "protected_project": False, "cross_project_allowed": False}
        }
        self.initial_status = {
            "protocol_version": "1", "state": "REVIEW_REQUESTED", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 5, "head": "abcdef123456", "request": "independent_review"
        }
        with open(self.status_file, "w") as f: json.dump(self.initial_status, f)

    def tearDown(self):
        self.temp_dir.cleanup()
        if "AGENT_BRIDGE_DIR" in os.environ: del os.environ["AGENT_BRIDGE_DIR"]

    def test_review_request_transitions_to_waiting(self):
        relay_adapter.handle_review_request(self.mock_profile)
        with open(self.status_file, "r") as f: self.assertEqual(json.load(f)["state"], "WAITING_FOR_REVIEW")

    @unittest.mock.patch('relay_adapter.execute_stop_protocol')
    def test_gpt_review_triple_head_match_pass_triggers_stop_protocol(self, mock_exec):
        relay_adapter.handle_review_request(self.mock_profile)
        with open(self.status_file, "r") as f: req_id = json.load(f)["request_id"]
        with open(self.review_file, "w") as f: f.write(f"REVIEW_REQUEST_ID: {req_id}\nVERDICT: PASS\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 5\nHEAD: abcdef123456\nSUMMARY:\nLooks good.\nACTIONS:\n")
        relay_adapter.handle_gpt_review_return(self.mock_profile, current_head="abcdef123456")
        with open(self.status_file, "r") as f: self.assertEqual(json.load(f)["state"], "WAITING_PO_AUTH")
        mock_exec.assert_called_once()

    def test_gpt_review_missing_current_head_fails_closed(self):
        relay_adapter.handle_review_request(self.mock_profile)
        with open(self.status_file, "r") as f: req_id = json.load(f)["request_id"]
        with open(self.review_file, "w") as f: f.write(f"REVIEW_REQUEST_ID: {req_id}\nVERDICT: PASS\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 5\nHEAD: abcdef123456\n")
        relay_adapter.handle_gpt_review_return(self.mock_profile, current_head=None)
        with open(self.status_file, "r") as f: self.assertEqual(json.load(f)["state"], "WAITING_FOR_REVIEW")

    @unittest.mock.patch('subprocess.run')
    def test_execute_stop_protocol_success(self, mock_run):
        status = {"protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456"}
        with open(self.status_file, "w") as f: json.dump(status, f)
        
        def side_effect(*args, **kwargs):
            if args[0][0] == "gh":
                return unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456"}', returncode=0)
            elif any("neutral_relay.py" in arg for arg in args[0]):
                with open(self.status_file, "r") as f: st = json.load(f)
                with open(self.review_file, "w") as f:
                    f.write(f"REVIEW_REQUEST_ID: {st['stop_episode']['request_id']}\nREPO: {st['repo']}\nPR: 42\nHEAD: abcdef123456\nACK: status_report_received\n")
                return unittest.mock.Mock(returncode=0)
        
        mock_run.side_effect = side_effect
        relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        with open(self.status_file, "r") as f: updated = json.load(f)
        self.assertTrue(updated["stop_episode"]["acked"])
        self.assertTrue(os.path.exists(relay_adapter.get_request_file()))

    @unittest.mock.patch('subprocess.run')
    def test_execute_stop_protocol_idempotent_duplicate_suppressed(self, mock_run):
        status = {
            "protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456",
            "stop_episode": {"request_id": "test-req-123", "state": "WAITING_PO_AUTH", "head": "abcdef123456", "pr": 42, "acked": True}
        }
        with open(self.status_file, "w") as f: json.dump(status, f)
        mock_run.return_value = unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456"}', returncode=0)
        
        with self.assertRaises(SystemExit) as cm:
            relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        self.assertEqual(cm.exception.code, 0) # Exits 0 on idempotent skip
        mock_run.assert_called_once() # Only called gh pr view, not neutral_relay

    @unittest.mock.patch('subprocess.run')
    def test_execute_stop_protocol_reconciles_unknown_result(self, mock_run):
        status = {
            "protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456",
            "stop_episode": {"request_id": "test-req-123", "state": "WAITING_PO_AUTH", "head": "abcdef123456", "pr": 42, "acked": False}
        }
        with open(self.status_file, "w") as f: json.dump(status, f)
        
        def side_effect(*args, **kwargs):
            if args[0][0] == "gh":
                return unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456"}', returncode=0)
            elif any("neutral_relay.py" in arg for arg in args[0]):
                with open(self.review_file, "w") as f:
                    f.write("REVIEW_REQUEST_ID: test-req-123\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 42\nHEAD: abcdef123456\nACK: status_report_received\n")
                return unittest.mock.Mock(returncode=0)
        
        mock_run.side_effect = side_effect
        relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        with open(self.status_file, "r") as f: updated = json.load(f)
        self.assertTrue(updated["stop_episode"]["acked"])
        self.assertEqual(updated["stop_episode"]["request_id"], "test-req-123") # Didn't generate new UUID
