import unittest
import os
import json
import tempfile
import sys
import asyncio

# Ensure neutral_relay can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import neutral_relay


class TestResponseCompletionTracker(unittest.TestCase):
    def snapshot(self, text, *, user_count=2, last_user_text="RID-1", soft=False, has_assistant=True):
        return {
            "userCount": user_count,
            "lastUserText": last_user_text,
            "text": text,
            "hasAssistant": has_assistant,
            "softGenerating": soft,
        }

    def test_stable_completed_response_with_stale_streaming_marker(self):
        tracker = neutral_relay.ResponseCompletionTracker()
        snap = self.snapshot("VERDICT: PASS", soft=True)
        self.assertEqual(tracker.observe(snap, 1, "RID-1", now=0), (False, ""))
        self.assertEqual(tracker.observe(snap, 1, "RID-1", now=4), (False, ""))
        self.assertEqual(tracker.observe(snap, 1, "RID-1", now=10), (True, "VERDICT: PASS"))

    def test_genuinely_streaming_response_keeps_resetting_settle_window(self):
        tracker = neutral_relay.ResponseCompletionTracker()
        for now, text in [(0, "V"), (2, "VERDICT"), (4, "VERDICT: PASS")]:
            self.assertEqual(
                tracker.observe(self.snapshot(text, soft=True), 1, "RID-1", now=now),
                (False, ""),
            )

    def test_persisting_stop_button_soft_signal_does_not_block_stable_text_forever(self):
        tracker = neutral_relay.ResponseCompletionTracker()
        snap = self.snapshot("Done", soft=True)
        tracker.observe(snap, 1, "RID-1", now=0)
        tracker.observe(snap, 1, "RID-1", now=5)
        self.assertEqual(tracker.observe(snap, 1, "RID-1", now=10), (True, "Done"))

    def test_normal_short_response_uses_normal_settle_window(self):
        tracker = neutral_relay.ResponseCompletionTracker()
        snap = self.snapshot("Short answer", soft=False)
        tracker.observe(snap, 1, "RID-1", now=0)
        tracker.observe(snap, 1, "RID-1", now=2)
        self.assertEqual(tracker.observe(snap, 1, "RID-1", now=4), (True, "Short answer"))

    def test_long_conversation_user_count_has_no_turn_ceiling(self):
        tracker = neutral_relay.ResponseCompletionTracker()
        snap = self.snapshot("PASS", user_count=26, soft=False)
        tracker.observe(snap, 25, "RID-1", now=0)
        tracker.observe(snap, 25, "RID-1", now=2)
        self.assertEqual(tracker.observe(snap, 25, "RID-1", now=4), (True, "PASS"))

    def test_never_stable_never_completes(self):
        tracker = neutral_relay.ResponseCompletionTracker()
        for now in range(0, 30, 2):
            complete, text = tracker.observe(
                self.snapshot(f"changing-{now}", soft=True),
                1,
                "RID-1",
                now=now,
            )
            self.assertFalse(complete)
            self.assertEqual(text, "")

    def test_correlation_still_requires_intended_user_turn(self):
        tracker = neutral_relay.ResponseCompletionTracker()
        snap = self.snapshot("PASS", user_count=1, last_user_text="OLD-RID", soft=False)
        for now in (0, 2, 4, 10):
            self.assertEqual(tracker.observe(snap, 1, "RID-1", now=now), (False, ""))


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
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: test/repo\nPR: 1\nHEAD: abc\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        ret = asyncio.run(neutral_relay.run_relay(args))
        
        self.assertEqual(ret, 0)
        self.assertTrue(os.path.exists(self.out_path))
        with open(self.out_path, "r") as f:
            content = f.read()
            self.assertIn("REVIEW_REQUEST_ID: 12345", content)

    def test_unknown_repo_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: unknown/repo\nPR: 1\nHEAD: abc\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        ret = asyncio.run(neutral_relay.run_relay(args))
        
        self.assertEqual(ret, 1)
        self.assertFalse(os.path.exists(self.out_path))

    def test_missing_request_id_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REPO: test/repo\nPR: 1\nHEAD: abc\n")

        args = self.Args(self.req_path, self.out_path, self.config_path, dry_run=True)
        ret = asyncio.run(neutral_relay.run_relay(args))
        
        self.assertEqual(ret, 1)
        self.assertFalse(os.path.exists(self.out_path))


if __name__ == '__main__':
    unittest.main()
