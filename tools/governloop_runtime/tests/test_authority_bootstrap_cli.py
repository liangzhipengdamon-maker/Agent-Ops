import argparse
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from governloop_runtime import authority, operator_channel
from governloop_runtime.__main__ import build_parser, cmd_setup_authority


BASE = "0123456789abcdef0123456789abcdef01234567"


class AuthorityBootstrapCLITests(unittest.TestCase):
    def _args(self, **overrides):
        values = {
            "task_id": "LEA-PILOT",
            "repo": "owner/repo",
            "branch": "feat/pilot",
            "baseline_sha": BASE,
            "authority_id": "pilot-authority",
            "allow_path": ["tools", "/tmp/external-evidence"],
            "operation": None,
            "trusted_reviewer": ["trusted-reviewer"],
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_parser_exposes_setup_authority_without_bind_authority(self):
        parser = build_parser()
        args = parser.parse_args([
            "setup-authority",
            "--task-id", "LEA-PILOT",
            "--repo", "owner/repo",
            "--branch", "feat/pilot",
            "--baseline-sha", BASE,
            "--allow-path", "tools",
            "--trusted-reviewer", "trusted-reviewer",
        ])
        self.assertEqual(args.command, "setup-authority")
        with self.assertRaises(SystemExit):
            parser.parse_args(["bind-authority"])

    def test_setup_authority_only_renders_non_authoritative_request(self):
        out = io.StringIO()
        with mock.patch("governloop_runtime.authority.authority_path",
                        return_value=operator_channel.Path("/runtime/.governloop/control/authority/LEA-PILOT.json")), \
             mock.patch("governloop_runtime.operator_channel.public_key_path",
                        return_value=operator_channel.Path("/runtime/.governloop/control/operator_authority.pub")), \
             mock.patch("builtins.open", side_effect=AssertionError("must not write files")), \
             redirect_stdout(out):
            rc = cmd_setup_authority(self._args())
        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["status"], "OPERATOR_ACTION_REQUIRED")
        self.assertFalse(result["authoritative"])
        self.assertFalse(result["mutations_performed"])
        self.assertEqual(result["payload"]["schema"], authority.SCHEMA)
        self.assertEqual(result["payload"]["allowed_paths"],
                         ["tools", "/tmp/external-evidence"])
        self.assertEqual(result["payload"]["allowed_operations"],
                         list(authority._ALLOWED_OPERATIONS))
        self.assertEqual(
            result["canonical_payload"],
            operator_channel.canonical_payload_bytes(result["payload"]).decode("utf-8"),
        )
        self.assertIn("external operator", result["next_required_external_action"])

    def test_explicit_operations_remain_scope_only(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_setup_authority(self._args(operation=["fix"]))
        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["payload"]["allowed_operations"], ["fix"])
        self.assertNotIn("merge", result["payload"]["allowed_operations"])
        self.assertNotIn("deploy", result["payload"]["allowed_operations"])

    def test_invalid_baseline_fails_without_rendering_authority_request(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_setup_authority(self._args(baseline_sha="short"))
        self.assertEqual(rc, 2)
        result = json.loads(out.getvalue())
        self.assertEqual(result["status"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
