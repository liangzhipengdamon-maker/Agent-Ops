import asyncio
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import neutral_relay
from neutral_relay import RuntimeIdentityError, verify_runtime_identity


class TestAge52RepoScopedRuntimeIdentity(unittest.TestCase):
    REPO_A = "example/repo-a"
    REPO_B = "liangzhipengdamon-maker/GovernLoop"
    CID_A = "6a796c47-5bbc-83ec-8a65-87c97397cf38"
    CID_B = "6a7d8ad7-cfa4-83ec-b67a-a1adbfbeb549"

    def make_config(self, profile_dir):
        return {
            "runtime": {
                "name": "GovernLoop",
                "cdp_port": 9233,
                "browser_profile": profile_dir,
                "runtime_marker": "governloop-runtime-v1",
            },
            "routes": {
                self.REPO_A: {
                    "conversation_url": f"https://chatgpt.com/c/{self.CID_A}",
                    "cdp_port": 9233,
                },
                self.REPO_B: {
                    "conversation_url": f"https://chatgpt.com/c/{self.CID_B}",
                    "cdp_port": 9233,
                },
            },
        }

    def write_marker(self, profile_dir):
        with open(os.path.join(profile_dir, "AGENTOPS_MARKER"), "w") as f:
            f.write("governloop-runtime-v1\n")

    def test_second_repo_resolves_its_own_conversation_not_first_route(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_marker(td)
            cfg = self.make_config(td)
            name, port, marker, cid = verify_runtime_identity(cfg, self.REPO_B)
            self.assertEqual(name, "GovernLoop")
            self.assertEqual(port, 9233)
            self.assertEqual(marker, "governloop-runtime-v1")
            self.assertEqual(cid, self.CID_B)

    def test_repo_a_and_repo_b_resolve_independently(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_marker(td)
            cfg = self.make_config(td)
            self.assertEqual(verify_runtime_identity(cfg, self.REPO_A)[3], self.CID_A)
            self.assertEqual(verify_runtime_identity(cfg, self.REPO_B)[3], self.CID_B)

    def test_unknown_repo_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_marker(td)
            cfg = self.make_config(td)
            with self.assertRaises(RuntimeIdentityError) as ctx:
                verify_runtime_identity(cfg, "unknown/repo")
            self.assertEqual(ctx.exception.code, "ROUTE_NOT_CONFIGURED")

    def test_multi_route_without_repo_fails_closed_instead_of_using_first(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_marker(td)
            cfg = self.make_config(td)
            with self.assertRaises(RuntimeIdentityError) as ctx:
                verify_runtime_identity(cfg)
            self.assertEqual(ctx.exception.code, "RUNTIME_REPOSITORY_REQUIRED")

    def test_selected_repo_port_must_match_runtime_port(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_marker(td)
            cfg = self.make_config(td)
            cfg["routes"][self.REPO_B]["cdp_port"] = 9222
            with self.assertRaises(RuntimeIdentityError) as ctx:
                verify_runtime_identity(cfg, self.REPO_B)
            self.assertEqual(ctx.exception.code, "WRONG_BROWSER_RUNTIME")

    def test_unrelated_route_port_does_not_define_selected_repo_identity(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_marker(td)
            cfg = self.make_config(td)
            cfg["routes"][self.REPO_A]["cdp_port"] = 9999
            # Repo B is still exactly bound to the canonical runtime and must
            # not inherit repo A's unrelated route identity or port.
            self.assertEqual(verify_runtime_identity(cfg, self.REPO_B)[3], self.CID_B)

    def test_single_route_legacy_call_remains_supported(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_marker(td)
            cfg = self.make_config(td)
            cfg["routes"] = {self.REPO_B: cfg["routes"][self.REPO_B]}
            self.assertEqual(verify_runtime_identity(cfg)[3], self.CID_B)

    def test_run_relay_uses_requested_repo_identity_in_multi_route_config(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_marker(td)
            config_path = os.path.join(td, "config.json")
            request_path = os.path.join(td, "request.txt")
            output_path = os.path.join(td, "out.md")
            with open(config_path, "w") as f:
                json.dump(self.make_config(td), f)
            with open(request_path, "w") as f:
                f.write(
                    "REVIEW_REQUEST_ID: AGE52-entrypoint\n"
                    f"REPO: {self.REPO_B}\n"
                    "PR: 70\n"
                    "HEAD: abc123\n"
                    "REQUEST: independent_review\n"
                )
            args = type("Args", (), {
                "request_file": request_path,
                "output_file": output_path,
                "config_file": config_path,
                "dry_run": True,
                "timeout": 5,
                "max_send_attempts": 2,
            })()
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                ret = asyncio.run(neutral_relay.run_relay(args))
            self.assertEqual(ret, 0)
            out = captured.getvalue()
            self.assertIn(f"EXPECTED_CONVERSATION_ID: {self.CID_B}", out)
            self.assertNotIn(f"EXPECTED_CONVERSATION_ID: {self.CID_A}", out)
            self.assertFalse(os.path.exists(output_path))


if __name__ == "__main__":
    unittest.main()
