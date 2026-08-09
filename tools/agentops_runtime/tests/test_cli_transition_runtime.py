import unittest
import os
import sys
import json
import tempfile
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import agentops_runtime.__main__ as cli
from transition_controller import route_decision


class TestCliTransitionRuntimePath(unittest.TestCase):
    """Verifies the CLI/runtime entry point (not direct function calls)."""

    def _sections(self):
        return {
            "Task": "CLI transition E2E",
            "Fixed behavior": "notify before WAITING_PO_AUTH",
            "Implementation": "__main__.py transition",
            "Live validation evidence": "via CLI runtime path",
            "Requirements verification": "all met",
            "PR/branch/HEAD": "pr / branch / head",
            "CI": "pass",
            "Deliverable": "docs/plans/X.md",
            "Boundaries": "no merge, no deploy",
        }

    def _write_sections(self, td):
        path = os.path.join(td, "sections.json")
        with open(path, "w") as f:
            json.dump(self._sections(), f)
        return path

    def test_high_routes_through_notify_via_cli(self):
        """HIGH via the CLI entry must invoke transition_with_po_notify
        (the runtime stop path), NOT just route_decision()."""
        with tempfile.TemporaryDirectory() as td:
            sections_path = self._write_sections(td)
            with mock.patch("agentops_runtime.__main__.query_live_pr_head",
                            return_value="abcd1234") as mock_head, \
                 mock.patch("agentops_runtime.__main__.transition_with_po_notify") as mock_twpn:
                mock_twpn.return_value = {
                    "outcome": {"route": "WAITING_PO_AUTH", "risk": "HIGH",
                                "review": "PASS", "reason": "high_risk"},
                    "po_notify": {"status": "DELIVERED", "delivered": True},
                }
                rc = cli.main(["transition", "HIGH", "PASS",
                               "--repo", "o/r", "--pr", "7",
                               "--task-id", "AGE-X",
                               "--deliverable-path", "docs/plans/X.md",
                               "--deliverable-url", "https://github.com/o/r/blob/main/docs/plans/X.md",
                               "--output-dir", td,
                               "--task-state", os.path.join(td, "state.json"),
                               "--completion-sections-json", sections_path])
            self.assertEqual(rc, 0)
            mock_head.assert_called_once_with("o/r", "7")
            mock_twpn.assert_called_once()
            call_kwargs = mock_twpn.call_args.kwargs
            self.assertEqual(call_kwargs["risk_level"], "HIGH")
            self.assertEqual(call_kwargs["review_decision"], "PASS")
            self.assertEqual(call_kwargs["head"], "abcd1234")
            self.assertEqual(call_kwargs["deliverable_path"], "docs/plans/X.md")

    def test_high_fails_closed_when_live_head_unavailable(self):
        """If the live PR HEAD cannot be queried, the CLI fails closed
        (exit 2) and does NOT write WAITING_PO_AUTH or send notify."""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.__main__.query_live_pr_head",
                            return_value=None), \
                 mock.patch("agentops_runtime.__main__.transition_with_po_notify") as mock_twpn:
                rc = cli.main(["transition", "HIGH", "PASS",
                               "--repo", "o/r", "--pr", "7",
                               "--output-dir", td])
            self.assertEqual(rc, 2)
            mock_twpn.assert_not_called()
            self.assertFalse(os.path.exists(os.path.join(td, "state.json")))

    def test_high_requires_repo_and_pr(self):
        """HIGH without repo/pr fails closed."""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("agentops_runtime.__main__.transition_with_po_notify") as mock_twpn:
                rc = cli.main(["transition", "HIGH", "PASS", "--output-dir", td])
            self.assertEqual(rc, 2)
            mock_twpn.assert_not_called()

    def test_low_medium_unchanged_no_notify(self):
        """LOW / MEDIUM keep original behavior: route only, no notify."""
        for risk in ("LOW", "MEDIUM"):
            with tempfile.TemporaryDirectory() as td:
                with mock.patch("agentops_runtime.__main__.transition_with_po_notify") as mock_twpn:
                    rc = cli.main(["transition", risk, "PASS",
                                   "--repo", "o/r", "--pr", "7",
                                   "--output-dir", td])
                self.assertEqual(rc, 0)
                mock_twpn.assert_not_called()
        self.assertEqual(route_decision("LOW", "PASS").route, "AUTO_CONTINUE")
        self.assertEqual(route_decision("MEDIUM", "PASS").route, "GPT_DECISION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
