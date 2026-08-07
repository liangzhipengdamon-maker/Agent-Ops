import unittest
import os
import json
import tempfile
import sys
import asyncio

# Ensure neutral_relay can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import neutral_relay

class TestNeutralRelay(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")
        self.req_path = os.path.join(self.temp_dir.name, "request.txt")
        self.out_path = os.path.join(self.temp_dir.name, "out.md")

        # Setup valid config
        config = {
            "routes": {
                "test/repo": {
                    "conversation_url": "mock_url",
                    "cdp_port": 1234
                }
            }
        }
        with open(self.config_path, "w") as f:
            json.dump(config, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    class Args:
        def __init__(self, req, out, cfg, dry_run=False):
            self.request_file = req
            self.output_file = out
            self.config_file = cfg
            self.dry_run = dry_run

    def test_repo_route_parsing_and_dry_run(self):
        # Setup valid request
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: test/repo\nPR: 1\nHEAD: abc\nREQUEST: independent_review\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        ret = asyncio.run(neutral_relay.run_relay(args))
        
        self.assertEqual(ret, 0)
        # Dry-run should no longer generate an output file or fake PASS
        self.assertFalse(os.path.exists(self.out_path))

    def test_unknown_repo_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: unknown/repo\nPR: 1\nHEAD: abc\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        ret = asyncio.run(neutral_relay.run_relay(args))
        
        self.assertEqual(ret, 1)
        self.assertFalse(os.path.exists(self.out_path))

    def test_missing_request_id_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REPO: test/repo\nPR: 1\nHEAD: abc\nREQUEST: independent_review\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        ret = asyncio.run(neutral_relay.run_relay(args))
        
        self.assertEqual(ret, 1)
        self.assertFalse(os.path.exists(self.out_path))

    def test_missing_pr_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: test/repo\nHEAD: abc\nREQUEST: independent_review\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        self.assertEqual(asyncio.run(neutral_relay.run_relay(args)), 1)
        
    def test_missing_head_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: test/repo\nPR: 1\nREQUEST: independent_review\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        self.assertEqual(asyncio.run(neutral_relay.run_relay(args)), 1)

    def test_missing_request_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: test/repo\nPR: 1\nHEAD: abc\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        self.assertEqual(asyncio.run(neutral_relay.run_relay(args)), 1)

    def test_empty_field_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: \nPR: 1\nHEAD: abc\nREQUEST: independent_review\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        self.assertEqual(asyncio.run(neutral_relay.run_relay(args)), 1)

    def test_extraction_logic(self):
        req_id = "abc-123"
        # A. History has PASS with req_id, but latest doesn't -> Reject
        msgs = [f"REVIEW_REQUEST_ID: {req_id} PASS", "Sorry, error"]
        self.assertIsNone(neutral_relay.extract_latest_assistant_response(msgs, req_id))
        
        # B. History has old ID, latest has current ID -> Extract latest only
        msgs = ["REVIEW_REQUEST_ID: old-id PASS", f"REVIEW_REQUEST_ID: {req_id} PASS-NEW"]
        self.assertEqual(neutral_relay.extract_latest_assistant_response(msgs, req_id), f"REVIEW_REQUEST_ID: {req_id} PASS-NEW")
        
        # C. Latest does not have current ID -> Fail closed
        msgs = ["Just chatting", "No ID here"]
        self.assertIsNone(neutral_relay.extract_latest_assistant_response(msgs, req_id))
        
        # D. Ensure it returns ONLY the latest message, not the history
        msgs = ["User: Hi", "Assistant: Hello", f"REVIEW_REQUEST_ID: {req_id}"]
        self.assertEqual(neutral_relay.extract_latest_assistant_response(msgs, req_id), f"REVIEW_REQUEST_ID: {req_id}")

if __name__ == '__main__':
    unittest.main()
