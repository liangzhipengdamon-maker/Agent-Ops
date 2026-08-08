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

    @unittest.mock.patch('time.sleep')
    @unittest.mock.patch('subprocess.run')
    def test_stop_protocol_mismatched_ack_does_not_exit(self, mock_run, mock_sleep):
        status = {
            "protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456",
            "stop_episode": {"request_id": "test-req-123", "state": "WAITING_PO_AUTH", "head": "abcdef123456", "pr": 42, "acked": False}
        }
        with open(self.status_file, "w") as f: json.dump(status, f)

        calls = {"relay": 0}
        def side_effect(*args, **kwargs):
            if args[0][0] == "gh":
                return unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456", "merged": false}', returncode=0)
            elif any("neutral_relay.py" in arg for arg in args[0]):
                calls["relay"] += 1
                if calls["relay"] == 1:
                    # First: WRONG request_id ACK, must NOT exit
                    with open(self.review_file, "w") as f:
                        f.write("REVIEW_REQUEST_ID: wrong-id\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 42\nHEAD: abcdef123456\nACK: status_report_received\n")
                else:
                    # Second: correct ACK, protocol should finish
                    with open(self.review_file, "w") as f:
                        f.write("REVIEW_REQUEST_ID: test-req-123\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 42\nHEAD: abcdef123456\nACK: status_report_received\n")
                return unittest.mock.Mock(returncode=0)

        mock_run.side_effect = side_effect
        relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        with open(self.status_file, "r") as f: updated = json.load(f)
        self.assertTrue(updated["stop_episode"]["acked"])
        self.assertGreaterEqual(calls["relay"], 2)

    @unittest.mock.patch('time.sleep')
    @unittest.mock.patch('subprocess.run')
    def test_stop_protocol_wrong_binding_ack_does_not_exit(self, mock_run, mock_sleep):
        status = {
            "protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456",
            "stop_episode": {"request_id": "test-req-123", "state": "WAITING_PO_AUTH", "head": "abcdef123456", "pr": 42, "acked": False}
        }
        with open(self.status_file, "w") as f: json.dump(status, f)

        calls = {"relay": 0}
        def side_effect(*args, **kwargs):
            if args[0][0] == "gh":
                return unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456", "merged": false}', returncode=0)
            elif any("neutral_relay.py" in arg for arg in args[0]):
                calls["relay"] += 1
                if calls["relay"] == 1:
                    # First: WRONG PR binding ACK, must NOT exit
                    with open(self.review_file, "w") as f:
                        f.write("REVIEW_REQUEST_ID: test-req-123\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 99\nHEAD: abcdef123456\nACK: status_report_received\n")
                else:
                    with open(self.review_file, "w") as f:
                        f.write("REVIEW_REQUEST_ID: test-req-123\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 42\nHEAD: abcdef123456\nACK: status_report_received\n")
                return unittest.mock.Mock(returncode=0)

        mock_run.side_effect = side_effect
        relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        with open(self.status_file, "r") as f: updated = json.load(f)
        self.assertTrue(updated["stop_episode"]["acked"])
        self.assertGreaterEqual(calls["relay"], 2)

    @unittest.mock.patch('time.sleep')
    @unittest.mock.patch('subprocess.run')
    def test_remote_readback_binds_canonical_repo(self, mock_run, mock_sleep):
        status = {
            "protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456",
            "stop_episode": {"request_id": "test-req-123", "state": "WAITING_PO_AUTH", "head": "abcdef123456", "pr": 42, "acked": False}
        }
        with open(self.status_file, "w") as f: json.dump(status, f)

        gh_calls = []
        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd[0] == "gh":
                gh_calls.append(cmd)
                return unittest.mock.Mock(stdout='{"headRefOid": "abcdef123456", "merged": false}', returncode=0)
            elif any("neutral_relay.py" in arg for arg in cmd):
                with open(self.review_file, "w") as f:
                    f.write("REVIEW_REQUEST_ID: test-req-123\nREPO: liangzhipengdamon-maker/Agent-Ops\nPR: 42\nHEAD: abcdef123456\nACK: status_report_received\n")
                return unittest.mock.Mock(returncode=0)

        mock_run.side_effect = side_effect
        relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")

        self.assertEqual(len(gh_calls), 1)
        gh_cmd = gh_calls[0]
        self.assertIn("--repo", gh_cmd)
        self.assertIn("liangzhipengdamon-maker/Agent-Ops", gh_cmd)

    @unittest.mock.patch('time.sleep')
    @unittest.mock.patch('subprocess.run')
    def test_execute_stop_protocol_non_stop_state_rejected(self, mock_run, mock_sleep):
        status = {
            "protocol_version": "1.0", "state": "REVIEW_REQUESTED", "repo": "liangzhipengdamon-maker/Agent-Ops", "pr": 42, "head": "abcdef123456"
        }
        with open(self.status_file, "w") as f: json.dump(status, f)

        with self.assertRaises(SystemExit) as cm:
            relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()

    @unittest.mock.patch('time.sleep')
    @unittest.mock.patch('subprocess.run')
    def test_execute_stop_protocol_missing_envelope_rejected(self, mock_run, mock_sleep):
        status = {
            "protocol_version": "1.0", "state": "WAITING_PO_AUTH", "repo": "liangzhipengdamon-maker/Agent-Ops", "head": "abcdef123456"
        }
        with open(self.status_file, "w") as f: json.dump(status, f)

        with self.assertRaises(SystemExit) as cm:
            relay_adapter.execute_stop_protocol(self.mock_profile, "Test summary", "NONE")
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()
