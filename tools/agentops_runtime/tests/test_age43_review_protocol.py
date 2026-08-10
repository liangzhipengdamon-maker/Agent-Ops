import json
import os
import sys
import tempfile
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
        self.assertEqual(out["marker"], LEGACY_REVIEW_MARKER)

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

    def test_active_request_marker_is_persisted_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(relay_client._persist_review_request(
                td, self.REPO, self.PR, self.HEAD, self.REQ))
            path = os.path.join(td, f"review_request_{self.PR}_{self.HEAD}.json")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["review_request_id"], self.REQ)
            self.assertEqual(data["repo"], self.REPO)
            self.assertEqual(data["pr"], self.PR)
            self.assertEqual(data["head"], self.HEAD)
            self.assertEqual(data["request"], "independent_review")


class TestGithubReviewIntakeCanonicalMarker(unittest.TestCase):
    HEAD = "abc123def"
    REQ = "AUTO_REVIEW_exact"
    REPO = "o/r"
    PR = 1

    def setUp(self):
        p = mock.patch("agentops_runtime.review_intake.trusted_reviewers",
                       return_value={"reviewer"})
        p.start()
        self.addCleanup(p.stop)

    def _body(self, marker="GOVERNLOOP_REVIEW: PASS", *, req=None,
              repo=None, pr=None, head=None):
        req = self.REQ if req is None else req
        repo = self.REPO if repo is None else repo
        pr = str(self.PR) if pr is None else str(pr)
        head = self.HEAD if head is None else head
        return (
            f"{marker}\n"
            f"REVIEW_REQUEST_ID: {req}\n"
            f"REPO: {repo}\n"
            f"PR: {pr}\n"
            f"HEAD: {head}"
        )

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

    def _review(self, body):
        return review_from_github(
            self.REPO, self.PR, self.HEAD,
            self._pr([{"state": "COMMENTED", "body": body}]),
            expected_request_id=self.REQ)

    def test_canonical_formal_pass_requires_full_exact_envelope(self):
        out = self._review(self._body())
        self.assertEqual(out.decision, "PASS")

    def test_legacy_formal_pass_requires_same_full_envelope(self):
        out = self._review(self._body(marker="AGENTOPS_REVIEW: PASS"))
        self.assertEqual(out.decision, "PASS")

    def test_missing_request_id_fails_closed(self):
        body = (
            "GOVERNLOOP_REVIEW: PASS\n"
            f"REPO: {self.REPO}\nPR: {self.PR}\nHEAD: {self.HEAD}"
        )
        self.assertEqual(self._review(body).decision, "INCOMPLETE")

    def test_mismatched_request_id_fails_closed(self):
        self.assertEqual(
            self._review(self._body(req="AUTO_REVIEW_other")).decision,
            "INCOMPLETE")

    def test_mismatched_repo_fails_closed(self):
        self.assertEqual(
            self._review(self._body(repo="other/repo")).decision,
            "INCOMPLETE")

    def test_mismatched_pr_fails_closed(self):
        self.assertEqual(
            self._review(self._body(pr=99)).decision,
            "INCOMPLETE")

    def test_missing_active_request_fails_closed(self):
        out = review_from_github(
            self.REPO, self.PR, self.HEAD,
            self._pr([{"state": "COMMENTED", "body": self._body()}]),
            expected_request_id="")
        self.assertEqual(out.decision, "INCOMPLETE")

    def test_duplicate_binding_field_fails_closed(self):
        body = self._body() + f"\nREPO: {self.REPO}"
        self.assertEqual(self._review(body).decision, "INCOMPLETE")

    def test_ambiguous_latest_bound_formal_fails_closed(self):
        out = review_from_github(
            self.REPO, self.PR, self.HEAD,
            self._pr([{
                "state": "COMMENTED",
                "submittedAt": "2026-08-10T01:00:00Z",
                "body": self._body(),
            }, {
                "state": "COMMENTED",
                "submittedAt": "2026-08-10T02:00:00Z",
                "body": self._body(
                    marker="GOVERNLOOP_REVIEW: PASS\nAGENTOPS_REVIEW: PASS"),
            }]),
            expected_request_id=self.REQ)
        self.assertEqual(out.decision, "INCOMPLETE")

    def test_stale_head_fails_closed(self):
        self.assertEqual(
            self._review(self._body(head="oldhead")).decision,
            "INCOMPLETE")

    def test_untrusted_canonical_fails_closed(self):
        out = review_from_github(
            self.REPO, self.PR, self.HEAD,
            self._pr([{
                "state": "COMMENTED",
                "author": {"login": "attacker"},
                "body": self._body(),
            }]),
            expected_request_id=self.REQ)
        self.assertEqual(out.decision, "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
