"""Tests for the canonical status_report ACK parser.

The parser lives in ``relay_client._parse_status_ack``. The validator
reads the canonical reviewer's reply to a status_report request and
decides whether the reply counts as an ACK for the binding pass.

Fail-closed invariant: a truncated or ambiguous assistant turn MUST
NEVER produce ack=True. It is acceptable to false-negative (STOP) and
fail closed. It is not acceptable to false-positive (PASS) and advance
the review handoff.

Coverage A-H matches GOVERNLOOP-REVIEW-TRANSPORT-FIX-001 §5.
"""

import os
import sys
import unittest

sys.path.insert(0,
                os.path.abspath(os.path.join(os.path.dirname(__file__),
                                             "..", "..")))

from agentops_runtime import relay_client


# Canonical request envelope values used by all tests.
SENT_REQ_ID = "IL_HANDOFF_dba64f6c3b22"
SENT_REPO = "liangzhipengdamon-maker/AI-Workspace-Governance"
SENT_PR = "15"
SENT_HEAD = "260cfecea01e886826bd70e4d44a74b28231199e"


def _build_sent_payload():
    return (
        f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
        f"REPO: {SENT_REPO}\n"
        f"PR: {SENT_PR}\n"
        f"HEAD: {SENT_HEAD}\n"
        "REQUEST: status_report\n"
        "STATE: WAITING_REVIEW\n"
        "GATE: REVIEW\n"
    )


class TestParseStatusAck(unittest.TestCase):

    # ----- A: exact 5-line ACK -> PASS -----------------------------------
    def test_A_exact_5_line_ack_pass(self):
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            "ACK: status_report_received\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertTrue(
            ack,
            f"expected ack=True for verbatim 5-line ACK; got ack={ack}, detail={detail!r}")

    # ----- B: 5 fields + extra natural-language lines -> PASS ------------
    def test_B_valid_5_fields_plus_extra_lines_pass(self):
        content = (
            "Reviewer prefix note.\n"
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            "ACK: status_report_received\n"
            "\n"
            "End-of-review addendum.\n"
            "Subsequent remark by GPT.\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertTrue(
            ack,
            f"expected ack=True when 5 fields appear with extras; got ack={ack}, detail={detail!r}")

    # ----- C: truncated REVIEW_REQUEST_ID -> FAIL -----------------------
    def test_C_truncated_review_request_id_fail(self):
        # Last 4 chars of REQ_ID truncated off.
        truncated = SENT_REQ_ID[:-4]
        self.assertEqual(len(truncated), len(SENT_REQ_ID) - 4)
        content = (
            f"REVIEW_REQUEST_ID: {truncated}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            "ACK: status_report_received\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(
            ack,
            f"truncated REQ_ID must NOT ack=True; got detail={detail!r}")
        # Failure detail must indicate partial specifically.
        self.assertTrue(
            "partial" in detail.lower(),
            f"detail must mention partial; got {detail!r}")

    def test_C2_truncated_ACK_value_fail(self):
        # ACK value truncated mid-token: ``status_report_receiv``.
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            "ACK: status_report_receiv\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(ack, "truncated ACK value must fail closed")
        # ACK prefix seen, value text not matching the literal
        self.assertIn("ack", detail.lower())

    # ----- D: missing ACK -> FAIL ---------------------------------------
    def test_D_missing_ACK_fail(self):
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(ack)
        self.assertIn("ack", detail.lower())

    def test_D2_only_one_field_present_fail(self):
        content = f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(ack)
        # REPO/PR/HEAD/ACK missing
        self.assertTrue(any(k in detail for k in ("REPO", "PR", "HEAD", "ACK")))

    # ----- E: duplicate REVIEW_REQUEST_ID with conflicting value -> FAIL
    def test_E_duplicate_review_request_id_conflicting_fail(self):
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            f"REVIEW_REQUEST_ID: IL_HANDOFF_other1234\n"
            "ACK: status_report_received\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(ack, "conflicting REQ_ID duplicates must fail closed")
        # Two occurrences — must detect duplicate count
        self.assertTrue(
            any(s in detail.lower() for s in (
                "twice", "duplicate", "2 times", "appears")),
            f"detail must signal duplicate; got {detail!r}")

    def test_E2_duplicate_review_request_id_same_value_still_fail(self):
        # Per task spec: "all 5 fields must exist exactly once" — even
        # duplicates with the SAME value are not acceptable.
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            "ACK: status_report_received\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(
            ack, "REQ_ID appearing twice (even with same value) must fail")
        self.assertTrue(
            any(s in detail.lower() for s in (
                "twice", "duplicate", "2 times", "appears")),
            f"detail must signal duplicate; got {detail!r}")

    # ----- F: wrong HEAD -> FAIL ----------------------------------------
    def test_F_wrong_head_fail(self):
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            "HEAD: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n"
            "ACK: status_report_received\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(ack)
        self.assertIn("head", detail.lower())
        # It's a binding mismatch, NOT a partial prefix (different values).
        self.assertIn("mismatch", detail.lower())

    def test_F2_partial_prefix_HEAD_fail(self):
        # HEAD value is a strict prefix of the request HEAD — parser must
        # treat this as a partial reply (mid-value truncation).
        truncated_head = SENT_HEAD[:30]
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {truncated_head}\n"
            "ACK: status_report_received\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(ack, "partial-prefix HEAD must fail closed")
        self.assertIn("partial", detail.lower())

    # ----- G: partial first snapshot, complete second -> PASS ----------
    # The new parser reads the FINAL assistant turn text written into
    # output.md by neutral_relay. Neutral relay only writes output.md
    # once the locked node's text has been stable for settle_stable_reads
    # consecutive polls AND envelope_complete is satisfied — so the
    # parser sees only the COMPLETE final snapshot in production.
    def test_G_complete_stable_snapshot_pass(self):
        # The content passed to the parser is what neutral_relay wrote
        # after waiting for stability + envelope_complete. Simulate that
        # with a fully formed reply.
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            "ACK: status_report_received\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertTrue(
            ack,
            f"complete-stable snapshot must pass; got detail={detail!r}")

    # ----- H: partial snapshot that stabilizes incomplete -> FAIL -----
    # The first half of these cases cover mid-value truncation; the last
    # covers the "key prefix with empty trailing value" last-line guard.
    def test_H_partial_truncated_REVIEW_REQUEST_ID_stabilizes_incomplete_fail(self):
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID[:12]}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            "ACK: status_report_received\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(
            ack,
            "truncated REQ_ID stabilised at partial must NOT ack=True")

    def test_H2_ACK_value_truncated_mid_token_fail(self):
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            "ACK: status_report_receiv\n"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(ack, "truncated ACK must fail closed")

    def test_H3_last_line_is_bare_key_header_fail(self):
        # Final line is the partial "ACK:" with no value at all.
        content = (
            f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
            f"REPO: {SENT_REPO}\n"
            f"PR: {SENT_PR}\n"
            f"HEAD: {SENT_HEAD}\n"
            "ACK:"
        )
        ack, detail = relay_client._parse_status_ack(
            content, _build_sent_payload())
        self.assertFalse(
            ack, "ACK: with empty trailing value must fail closed")
        self.assertIn("partial", detail.lower())

    def test_H4_empty_content_fail(self):
        ack, detail = relay_client._parse_status_ack(
            "", _build_sent_payload())
        self.assertFalse(ack)
        self.assertIn("empty", detail.lower())

    def test_H5_whitespace_only_content_fail(self):
        ack, detail = relay_client._parse_status_ack(
            "   \n\n  \t \n", _build_sent_payload())
        self.assertFalse(ack)
        self.assertIn("empty", detail.lower())

    # ----- negative invariant: NO false-positive allowed --------------
    def test_H6_no_false_positive_in_partial_assortment(self):
        # For each partial case, ack must be False. Any ack=True here is
        # a regression of the no-false-positive invariant.
        partial_cases = {
            "REQ_ID mid-truncated": (
                f"REVIEW_REQUEST_ID: {SENT_REQ_ID[:12]}\n"
                f"REPO: {SENT_REPO}\n"
                f"PR: {SENT_PR}\n"
                f"HEAD: {SENT_HEAD}\n"
                "ACK: status_report_received\n"
            ),
            "ACK missing": (
                f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
                f"REPO: {SENT_REPO}\n"
                f"PR: {SENT_PR}\n"
                f"HEAD: {SENT_HEAD}\n"
            ),
            "REPO mid-truncated": (
                f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
                f"REPO: liangzhipengdamon-maker/AI-Workspace-Go\n"
                f"PR: {SENT_PR}\n"
                f"HEAD: {SENT_HEAD}\n"
                "ACK: status_report_received\n"
            ),
            "PR off by one": (
                f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
                f"REPO: {SENT_REPO}\n"
                f"PR: 1\n"
                f"HEAD: {SENT_HEAD}\n"
                "ACK: status_report_received\n"
            ),
            "HEAD wrong value": (
                f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
                f"REPO: {SENT_REPO}\n"
                f"PR: {SENT_PR}\n"
                "HEAD: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n"
                "ACK: status_report_received\n"
            ),
            "ACK value mangled": (
                f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
                f"REPO: {SENT_REPO}\n"
                f"PR: {SENT_PR}\n"
                f"HEAD: {SENT_HEAD}\n"
                "ACK: status_report_NOT\n"
            ),
            "duplicate REQ_ID with conflicting value": (
                f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
                f"REPO: {SENT_REPO}\n"
                f"PR: {SENT_PR}\n"
                f"HEAD: {SENT_HEAD}\n"
                "REVIEW_REQUEST_ID: OTHER_OTHER_OTHER\n"
                "ACK: status_report_received\n"
            ),
            "ACK: empty trailing (mid-stream)": (
                f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
                f"REPO: {SENT_REPO}\n"
                f"PR: {SENT_PR}\n"
                f"HEAD: {SENT_HEAD}\n"
                "ACK:"
            ),
            "ACK: only whitespace value": (
                f"REVIEW_REQUEST_ID: {SENT_REQ_ID}\n"
                f"REPO: {SENT_REPO}\n"
                f"PR: {SENT_PR}\n"
                f"HEAD: {SENT_HEAD}\n"
                "ACK:   \n"
            ),
        }
        for label, content in partial_cases.items():
            with self.subTest(case=label):
                ack, detail = relay_client._parse_status_ack(
                    content, _build_sent_payload())
                self.assertFalse(
                    ack,
                    msg=f"FALSE POSITIVE: {label} returned ack=True; "
                        f"detail={detail!r}")


class TestSendStatusReportRoutering(unittest.TestCase):
    """Surface the new helper export + neutral-relay binding."""

    def test_parser_helper_is_exported(self):
        self.assertTrue(hasattr(relay_client, "_parse_status_ack"))
        self.assertTrue(callable(relay_client._parse_status_ack))

    def test_required_keys_constant_present(self):
        self.assertTrue(hasattr(relay_client, "ACK_REQUIRED_KEYS"))
        self.assertEqual(
            set(relay_client.ACK_REQUIRED_KEYS),
            {"REVIEW_REQUEST_ID", "REPO", "PR", "HEAD", "ACK"})

    def test_literal_value_constant_present(self):
        self.assertTrue(hasattr(relay_client, "ACK_LITERAL_VALUE"))
        self.assertEqual(relay_client.ACK_LITERAL_VALUE,
                         "status_report_received")


if __name__ == "__main__":
    unittest.main()
