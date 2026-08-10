import os
import sys
import unittest
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from agentops_runtime import relay_client
from agentops_runtime.review_intake import review_from_github
from agentops_runtime.review_protocol import (
    CANONICAL_REVIEW_MARKER,
    LEGACY_REVIEW_MARKER,
    parse_formal_review_verdict,
)


class TestReviewProtocolParser(unittest.TestCase):
    def test_canonical_pass(self):
        out = parse_formal_review_verdict("GOVERNLOOP_REVIEW: PASS")
        self.assertEqual(out.status, "VALID")
        self.assertEqual(out.marker, CANONICAL_REVIEW_MARKER)
        self.assertEqual(out.verdict, "PASS")

    def test_legacy_pass_compatibility(self):
        out = parse_formal_review_verdict("AGENTOPS_REVIEW: PASS")
        self.assertEqual(out.status, "VALID")
        self.assertEqual(out.marker, LEGACY_REVIEW_MARKER)
        self.assertEqual(out.verdict, "PASS")

    def test_duplicate_canonical_fails_closed(self):
        out = parse_formal_review_verdict(
            "GOVERNLOOP_REVIEW: PASS\nGOVERNLOOP_REVIEW: PASS")
        self.assertEqual(out.status, "INVALID")

    def test_mixed_canonical_legacy_same_verdict_fails_closed(self):
        out = parse_formal_review_verdict(
            "GOVERNLOOP_REVIEW: PASS\nAGENTOPS_REVIEW: PASS")
        self.assertEqual(out.status, "INVALID")

    def test_mixed_conflicting_verdicts_fail_closed(self):
        out = parse_formal_review_verdict(
            "GOVERNLOOP_REVIEW: PASS\nAGENTOPS_REVIEW: NOT_PASS")
        self.assertEqual(out.status, "INVALID")

    def test_invalid_verdict_fails_closed(self):
        out = parse_formal_review_verdict("GOVERNLOOP_REVIEW: APPROVE")
        self.assertEqual(out.status, "INVALID")


class TestRelayReviewResponse(unittest.TestCase):
    REPO = "o/r"
    PR = "7"
    HEAD = "abc123"
    REQ = "AUTO_REVIEW_test"

    def _response(self, marker_line, extra=""):
        return (
            f"{marker_line}\n"
            f"REVIEW_REQUEST_ID: {self.REQ}\n"
            f"REPO: {self.REPO}\n"
            f"PR: {self.PR}\n"
            f"HEAD: {self.HEAD}\n"
            f"{extra}"
        )

    def test_canonical_round_trip(self):
        out = relay_client.parse_review_response(
            self._response("GOVERNLOOP_REVIEW: PASS"),
            self.REPO, self.PR, self.HEAD, self.REQ)
        self.assertTrue(out["ok"])
        self.assertEqual(out["verdict"], "PASS")
        self.assertEqual(out["marker"], CANONICAL_REVIEW_MARKER)

    def test_legacy_round_trip(self):
        out = relay_client.parse_review_response(
            self._response("AGENTOPS_REVIEW: PASS"),
            self.REPO, self.PR, self.HEAD, self.REQ)
        self.assertTrue(out["ok"])
        self.assertEqual(out["verdict"], "PASS")
        self.assertEqual(out["marker"], LEGACY_REVIEW_MARKER)

    def test_changes_requested_retains_findings(self):
        out = relay_client.parse_review_response(
            self._response(
                "GOVERNLOOP_REVIEW: CHANGES_REQUESTED",
                "Finding A\nFinding B\n"),
            self.REPO, self.PR, self.HEAD, self.REQ)
        self.assertTrue(out["ok"])
        self.assertEqual(out["verdict"], "CHANGES_REQUESTED")
        self.assertEqual(out["findings"], ["Finding A", "Finding B"])

    def test_duplicate_marker_fails_closed(self):
        text = self._response(
            "GOVERNLOOP_REVIEW: PASS\nAGENTOPS_REVIEW: PASS")
        out = relay_client.parse_review_response(
            text, self.REPO, self.PR, self.HEAD, self.REQ)
        self.assertFalse(out["ok"])
        self.assertEqual(out["verdict"], "INCOMPLETE")

    def test_binding_mismatch_still_fails_closed(self):
        text = self._response("GOVERNLOOP_REVIEW: PASS")
        out = relay_client.parse_review_response(
            text, self.REPO, self.PR, "different", self.REQ)
        self.assertFalse(out["ok"])
        self.assertEqual(out["verdict"], "INCOMPLETE")


class TestGithubReviewIntakeCanonicalMarker(unittest.TestCase):
    HEAD = "abc123def"

    def setUp(self):
        p = mock.patch("agentops_runtime.review_intake.trusted_reviewers",
                       return_value={"reviewer"})
        p.start()
        self.addCleanup(p.stop)

    def _pr(self, reviews):
        normalized = []
        for review in reviews:
            item = dict(review)
            item.setdefault("author", {"login": "reviewer"})
            normalized.append(item)
        return {
            "reviewDecision": None,
            "mergeable": "MERGEABLE",
            "headRefOid": self.HEAD,
            "reviews": normalized,
        }

    def test_canonical_formal_pass_is_executable(self):
        out = review_from_github("o/r", 1, self.HEAD, self._pr([{
            "state": "COMMENTED",
            "body": f"GOVERNLOOP_REVIEW: PASS\nHEAD: {self.HEAD}",
        }]))
        self.assertEqual(out.decision, "PASS")

    def test_legacy_formal_pass_remains_executable(self):
        out = review_from_github("o/r", 1, self.HEAD, self._pr([{
            "state": "COMMENTED",
            "body": f"AGENTOPS_REVIEW: PASS\nHEAD: {self.HEAD}",
        }]))
        self.assertEqual(out.decision, "PASS")

    def test_ambiguous_latest_bound_formal_fails_closed(self):
        out = review_from_github("o/r", 1, self.HEAD, self._pr([{
            "state": "COMMENTED",
            "submittedAt": "2026-08-10T01:00:00Z",
            "body": f"GOVERNLOOP_REVIEW: PASS\nHEAD: {self.HEAD}",
        }, {
            "state": "COMMENTED",
            "submittedAt": "2026-08-10T02:00:00Z",
            "body": (
                "GOVERNLOOP_REVIEW: PASS\n"
                "AGENTOPS_REVIEW: PASS\n"
                f"HEAD: {self.HEAD}"
            ),
        }]))
        self.assertEqual(out.decision, "INCOMPLETE")
        self.assertTrue(out.fail_closed)

    def test_canonical_stale_head_fails_closed(self):
        out = review_from_github("o/r", 1, self.HEAD, self._pr([{
            "state": "COMMENTED",
            "body": "GOVERNLOOP_REVIEW: PASS\nHEAD: oldhead",
        }]))
        self.assertEqual(out.decision, "INCOMPLETE")
        self.assertTrue(out.fail_closed)

    def test_untrusted_canonical_fails_closed(self):
        out = review_from_github("o/r", 1, self.HEAD, self._pr([{
            "state": "COMMENTED",
            "author": {"login": "attacker"},
            "body": f"GOVERNLOOP_REVIEW: PASS\nHEAD: {self.HEAD}",
        }]))
        self.assertEqual(out.decision, "INCOMPLETE")
        self.assertTrue(out.fail_closed)


if __name__ == "__main__":
    unittest.main()
