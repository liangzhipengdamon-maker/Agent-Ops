import unittest
import unittest.mock
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
import relay_adapter

class TestExecuteStopProtocol(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["AGENT_BRIDGE_DIR"] = self.temp_dir.name
        self.status_file = relay_adapter.get_status_file()
        self.review_file = relay_adapter.get_review_file()
        self.mock_profile = {
            "project_identity": "test",
            "github": {"repository": "liangzhipengdamon-maker/Agent-Ops", "canonical_branch": "main"},
        }

    def tearDown(self):
        self.temp_dir.cleanup()
        if "AGENT_BRIDGE_DIR" in os.environ: del os.environ["AGENT_BRIDGE_DIR"]

    @unittest.mock.patch('subprocess.run')
    def test_execute_stop_protocol_success(self, mock_run):
        status = {"protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456"}
        with open(self.status_file, "w") as f: json.dump(status, f)
        
        def side_effect(*args, **kwargs):
            if args[0][0] == "gh":
                return unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456", "merged": false}', returncode=0)
            elif any("neutral_relay.py" in arg for arg in args[0]):
                with open(self.status_file, "r") as f: st = json.load(f)
                with open(self.review_file, "w") as f:
                    f.write(f"REVIEW_REQUEST_ID: {st['stop_episode']['request_id']}\nREPO: {st['repo']}\nPR: 42\nHEAD: abcdef123456\nACK: status_report_received\n")
                return unittest.mock.Mock(returncode=0)
        
        mock_run.side_effect = side_effect
        relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        with open(self.status_file, "r") as f: updated = json.load(f)
        self.assertTrue(updated["stop_episode"]["acked"])

    @unittest.mock.patch('subprocess.run')
    def test_execute_stop_protocol_idempotent_duplicate_suppressed(self, mock_run):
        status = {
            "protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456",
            "stop_episode": {"request_id": "test-req-123", "state": "WAITING_PO_AUTH", "head": "abcdef123456", "pr": 42, "acked": True}
        }
        with open(self.status_file, "w") as f: json.dump(status, f)
        mock_run.return_value = unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456", "merged": false}', returncode=0)
        
        with self.assertRaises(SystemExit) as cm:
            relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        self.assertEqual(cm.exception.code, 0)
        mock_run.assert_called_once()

    @unittest.mock.patch('subprocess.run')
    def test_execute_stop_protocol_done_requires_merged(self, mock_run):
        status = {"protocol_version": "1.0", "state": "DONE", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456"}
        with open(self.status_file, "w") as f: json.dump(status, f)
        mock_run.return_value = unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456", "merged": false}', returncode=0)
        
        with self.assertRaises(SystemExit) as cm:
            relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        self.assertEqual(cm.exception.code, 1)

    @unittest.mock.patch('subprocess.run')
    def test_execute_stop_protocol_reconciles_unknown_result(self, mock_run):
        status = {
            "protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456",
            "stop_episode": {"request_id": "test-req-123", "state": "WAITING_PO_AUTH", "head": "abcdef123456", "pr": 42, "acked": False}
        }
        with open(self.status_file, "w") as f: json.dump(status, f)
        
        def side_effect(*args, **kwargs):
            if args[0][0] == "gh":
                return unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456", "merged": false}', returncode=0)
            elif any("neutral_relay.py" in arg for arg in args[0]):
                with open(self.review_file, "w") as f:
                    f.write("REVIEW_REQUEST_ID: test-req-123\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 42\nHEAD: abcdef123456\nACK: status_report_received\n")
                return unittest.mock.Mock(returncode=0)
        
        mock_run.side_effect = side_effect
        relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        with open(self.status_file, "r") as f: updated = json.load(f)
        self.assertTrue(updated["stop_episode"]["acked"])
        self.assertEqual(updated["stop_episode"]["request_id"], "test-req-123")
