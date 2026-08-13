import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from governloop_runtime import operator_cli


class OperatorCliTests(unittest.TestCase):
    def test_parser_exposes_narrow_commands(self):
        parser = operator_cli.build_parser()
        self.assertEqual(parser.parse_args(["inspect", "--runtime-user", "builder"]).command, "inspect")
        args = parser.parse_args([
            "authorize", "--runtime-user", "builder",
            "--kind", "external_path", "--signed-document", "/tmp/signed.json",
        ])
        self.assertEqual(args.kind, "external_path")

    def test_same_uid_cannot_be_operator_for_runtime(self):
        account = SimpleNamespace(pw_uid=os.geteuid(), pw_dir="/tmp/runtime")
        with patch("governloop_runtime.operator_cli._account", return_value=account):
            with self.assertRaisesRegex(RuntimeError, "must differ"):
                operator_cli._root("builder")

    def test_authorize_rejects_wrong_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "signed.json"
            path.write_text(json.dumps({
                "payload": {"schema": "wrong-schema", "task_id": "T-1"},
                "ssh_signature": "-----BEGIN SSH SIGNATURE-----\n...",
            }), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "schema"):
                operator_cli._load_signed(path, "governloop-external-path-authority-v1")

    def test_inspect_is_read_only_parser_surface(self):
        args = operator_cli.build_parser().parse_args(["inspect", "--runtime-user", "builder"])
        self.assertFalse(hasattr(args, "signed_document"))
        self.assertFalse(hasattr(args, "authority_id"))


if __name__ == "__main__":
    unittest.main()
