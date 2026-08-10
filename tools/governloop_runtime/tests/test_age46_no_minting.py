import os
import sys
import unittest

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime.__main__ import build_parser


class TestDoctorNoAuthorityMinting(unittest.TestCase):
    def test_bind_authority_is_not_a_canonical_command(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["bind-authority"])

    def test_doctor_is_read_only_command_surface(self):
        args = build_parser().parse_args([
            "doctor", "--task-id", "AGE-X", "--repo", "owner/repo",
            "--no-reviewer-probe",
        ])
        self.assertEqual(args.command, "doctor")
        self.assertTrue(args.no_reviewer_probe)


if __name__ == "__main__":
    unittest.main()
