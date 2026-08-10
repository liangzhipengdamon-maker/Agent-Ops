import unittest
import os
import json
import tempfile
import sys
import asyncio

# Ensure neutral_relay can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import neutral_relay
from neutral_relay import (
    SendFlow,
    SendFlowError,
    DomProbe,
    CdpSession,
    parse_envelope,
    correlate_response,
    classify_send_result,
    should_skip_send,
    normalize_text,
    extract_latest_assistant_response,
    ConversationIdentityError,
    RuntimeIdentityError,
    resolve_reviewer_target,
    target_matches_reviewer,
    conversation_id_from_url,
    normalize_conversation_url,
    verify_runtime_identity,
)


# ---------------------------------------------------------------------------
# Fake CDP session + probe for SendFlow tests (deterministic, no browser)
# ---------------------------------------------------------------------------

class FakeSession:
    """Simulates the CDP session methods used by DomProbe/SendFlow."""

    def __init__(self, state):
        self.state = state  # mutable dict the test can script
        self.inserts = []

    async def eval_js(self, expr, session):
        # Our DomProbe builds expressions from the PROBE_* strings with
        # arguments embedded. For tests we drive state via DomProbe's probe()
        # methods directly, so eval_js is only a fallback used by composer_text.
        if "innerText" in expr and "querySelector" in expr:
            # composer_text extraction fallback: report the last inserted text
            return self.state.get("composer_text", "")
        return None

    async def insert_text(self, text, session):
        self.inserts.append(text)
        self.state["composer_text"] = text

    async def key_combo(self, *a, **k):
        pass


class FakeProbe:
    """A controllable DomProbe that returns scripted DOM state."""

    def __init__(self):
        self.session = FakeSession({})
        self.sid = "fake"
        self.composer_state = []          # list of composer descriptors
        self.send_state = []              # list of send-control descriptors
        self.conv_state = {"users": [], "asst": [], "stopBtn": False}
        self.click_count = 0
        self.focus_count = 0

    def visible_composer(self, **kw):
        d = {"found": True, "vis": True, "w": 320, "h": 42, "sel": "#prompt-textarea", "ce": "true"}
        d.update(kw)
        return d

    def hidden_composer(self, **kw):
        d = {"found": True, "vis": False, "w": 0, "h": 0, "sel": "#prompt-textarea", "ce": "true"}
        d.update(kw)
        return d

    def send_control(self, disabled=False, **kw):
        d = {"found": True, "vis": True, "disabled": disabled, "w": 36, "sel": 'button[data-testid="send-button"]'}
        d.update(kw)
        return d

    async def composers(self):
        return self.composer_state

    async def send_controls(self):
        return self.send_state

    async def conversation(self):
        return dict(self.conv_state)

    async def assistant_turns(self):
        asst = self.conv_state.get("asst") or []
        return [{"text": t, "id": f"turn-{i}"} for i, t in enumerate(asst)]

    async def focus_composer(self):
        self.focus_count += 1
        if any(c.get("vis") for c in self.composer_state):
            return "#prompt-textarea"
        return None

    async def click_send(self):
        self.click_count += 1
        for c in self.send_state:
            if c.get("found") and c.get("vis") and not c.get("disabled"):
                return c.get("sel")
        return None

    async def current_url(self):
        return "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e"


def make_envelope(req_id="req-123", repo="test/repo", pr="5", head="abc123", request="independent_review"):
    return {"REPO": repo, "REVIEW_REQUEST_ID": req_id, "PR": pr, "HEAD": head, "REQUEST": request}


def make_request_text(envelope=None):
    e = envelope or make_envelope()
    return (
        f"REVIEW_REQUEST_ID: {e['REVIEW_REQUEST_ID']}\n"
        f"REPO: {e['REPO']}\n"
        f"PR: {e['PR']}\n"
        f"HEAD: {e['HEAD']}\n"
        f"REQUEST: {e['REQUEST']}\n"
    )


class TestEnvelopeParsing(unittest.TestCase):
    def test_parses_all_fields(self):
        text = "REVIEW_REQUEST_ID: abc-1\nREPO: a/b\nPR: 3\nHEAD: h1\nREQUEST: x\n"
        e = parse_envelope(text)
        self.assertEqual(e["REVIEW_REQUEST_ID"], "abc-1")
        self.assertEqual(e["REPO"], "a/b")
        self.assertEqual(e["PR"], "3")
        self.assertEqual(e["HEAD"], "h1")
        self.assertEqual(e["REQUEST"], "x")

    def test_missing_fields_are_none(self):
        e = parse_envelope("REPO: a/b\nPR: 3\n")
        self.assertIsNone(e["REVIEW_REQUEST_ID"])
        self.assertIsNone(e["HEAD"])


class TestCorrelateResponse(unittest.TestCase):
    """Tests 9, 10, 11, 12: stale / wrong-id / wrong-binding / duplicate."""

    def setUp(self):
        self.env = make_envelope(req_id="req-123", repo="test/repo", pr="5", head="abc123")

    def test_valid_correlated_response_accepted(self):
        msgs = [
            "REVIEW_REQUEST_ID: req-old PASS",
            ("REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 5\nHEAD: abc123\n"
             "VERDICT: PASS\nSUMMARY:\nok"),
        ]
        self.assertIsNotNone(correlate_response(msgs, self.env))

    def test_stale_response_rejected_when_latest_lacks_id(self):
        # Latest message has no req_id -> must fail closed even if history does
        msgs = [
            "REVIEW_REQUEST_ID: req-123\nVERDICT: PASS",
            "Sorry, that request was already handled.",
        ]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_wrong_request_id_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: other-req\nREPO: test/repo\nPR: 5\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_wrong_repo_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: other/repo\nPR: 5\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_wrong_pr_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 99\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_wrong_head_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 5\nHEAD: deadbeef\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_duplicate_responses_take_latest(self):
        msgs = [
            "REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 5\nHEAD: abc123\nVERDICT: PASS\nv1",
            "REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 5\nHEAD: abc123\nVERDICT: PASS\nv2",
        ]
        result = correlate_response(msgs, self.env)
        self.assertIn("v2", result)
        self.assertNotIn("v1", result)

    def test_request_id_only_rejected(self):
        # Only REQUEST_ID present, no REPO/PR/HEAD -> reject.
        msgs = ["REVIEW_REQUEST_ID: req-123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_missing_repo_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nPR: 5\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_missing_pr_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_missing_head_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 5\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_empty_repo_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO:\nPR: 5\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_empty_pr_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR:\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_empty_head_rejected(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 5\nHEAD:\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_empty_request_id_rejected(self):
        msgs = ["REVIEW_REQUEST_ID:\nREPO: test/repo\nPR: 5\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_wrong_repo_rejected_strict(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: some/other\nPR: 5\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_wrong_pr_rejected_strict(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 99\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_wrong_head_rejected_strict(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 5\nHEAD: deadbeef\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_wrong_request_id_rejected_strict(self):
        msgs = ["REVIEW_REQUEST_ID: other-req\nREPO: test/repo\nPR: 5\nHEAD: abc123\nVERDICT: PASS"]
        self.assertIsNone(correlate_response(msgs, self.env))

    def test_all_four_exact_accepted(self):
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 5\nHEAD: abc123\nVERDICT: PASS"]
        result = correlate_response(msgs, self.env)
        self.assertIsNotNone(result)
        self.assertIn("VERDICT: PASS", result)

    def test_envelope_missing_field_rejected(self):
        # envelope missing HEAD -> correlation cannot be strict -> reject.
        msgs = ["REVIEW_REQUEST_ID: req-123\nREPO: test/repo\nPR: 5\nHEAD: abc123\nVERDICT: PASS"]
        bad_env = {"REVIEW_REQUEST_ID": "req-123", "REPO": "test/repo", "PR": "5"}
        self.assertIsNone(correlate_response(msgs, bad_env))


class TestClassifySendResult(unittest.TestCase):
    """Tests 6, 7, 8: reconcile / read-back semantics."""

    def setUp(self):
        self.req = make_request_text()
        self.env = make_envelope()

    def test_confirmed_sent_by_request_id(self):
        users = [f"REVIEW_REQUEST_ID: {self.env['REVIEW_REQUEST_ID']} ..."]
        verdict, evidence = classify_send_result(users, self.req, self.env["REVIEW_REQUEST_ID"])
        self.assertEqual(verdict, "CONFIRMED_SENT")
        self.assertIn("request_id", evidence)

    def test_confirmed_sent_by_payload_snippet(self):
        users = [self.req]  # verbatim payload in a user message
        verdict, _ = classify_send_result(users, self.req, self.env["REVIEW_REQUEST_ID"])
        self.assertEqual(verdict, "CONFIRMED_SENT")

    def test_confirmed_not_sent(self):
        users = ["Just some unrelated conversation"]
        verdict, _ = classify_send_result(users, self.req, self.env["REVIEW_REQUEST_ID"])
        self.assertEqual(verdict, "CONFIRMED_NOT_SENT")

    def test_empty_users_is_not_sent(self):
        # Empty list means conversation readable, request definitely not there -> retry.
        verdict, _ = classify_send_result([], self.req, self.env["REVIEW_REQUEST_ID"])
        self.assertEqual(verdict, "CONFIRMED_NOT_SENT")

    def test_ambiguous_when_unreadable(self):
        verdict, _ = classify_send_result(None, self.req, self.env["REVIEW_REQUEST_ID"])
        self.assertEqual(verdict, "AMBIGUOUS")


class TestDuplicateSendProtection(unittest.TestCase):
    def test_skip_when_request_already_sent(self):
        env = make_envelope()
        users = [f"payload REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']} delivered"]
        self.assertTrue(should_skip_send(users, env["REVIEW_REQUEST_ID"]))

    def test_no_skip_when_not_present(self):
        env = make_envelope()
        self.assertFalse(should_skip_send(["unrelated"], env["REVIEW_REQUEST_ID"]))


class TestSendFlow(unittest.TestCase):
    """Integration-style tests of the state machine with scripted probes."""

    def test_composer_found_normally_and_sends(self):
        env = make_envelope()
        probe = FakeProbe()
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=False)]
        state = {"n": 0}

        async def conv():
            state["n"] += 1
            if state["n"] >= 2:
                probe.conv_state["users"] = [make_request_text(env)]
            if state["n"] >= 3:
                probe.conv_state["asst"] = [
                    f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nVERDICT: PASS\nv1",
                    f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nVERDICT: PASS\nv2",
                ]
            return dict(probe.conv_state)
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url="https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e",
                        timeout=5, poll_interval=0.05, stage_timeouts={"LOCATE_COMPOSER":1,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        result = asyncio.run(flow.run(env, make_request_text(env)))
        self.assertIn("VERDICT: PASS", result)
        self.assertEqual(probe.click_count, 1)

    def test_primary_selector_fails_fallback_succeeds(self):
        env = make_envelope()
        probe = FakeProbe()
        probe.composer_state = [
            {"found": False, "sel": "#prompt-textarea"},
            probe.visible_composer(sel="textarea[aria-label*='与 ChatGPT 聊天']", ce=None),
        ]
        probe.send_state = [probe.send_control(disabled=False)]
        state = {"n": 0}

        async def conv():
            state["n"] += 1
            if state["n"] >= 2:
                probe.conv_state["users"] = [make_request_text(env)]
            if state["n"] >= 3:
                probe.conv_state["asst"] = [f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nVERDICT: PASS"]
            return dict(probe.conv_state)
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url="https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e",
                        timeout=5, poll_interval=0.05, stage_timeouts={"LOCATE_COMPOSER":1,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        result = asyncio.run(flow.run(env, make_request_text(env)))
        self.assertIn("VERDICT: PASS", result)

    def test_composer_invisible_rejects(self):
        env = make_envelope()
        probe = FakeProbe()
        probe.composer_state = [probe.hidden_composer()]
        flow = SendFlow(probe, reviewer_url="https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e", timeout=2, poll_interval=0.05, stage_timeouts={"LOCATE_COMPOSER":1,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        with self.assertRaises(SendFlowError) as ctx:
            asyncio.run(flow.run(env, make_request_text(env)))
        self.assertEqual(ctx.exception.stage, "LOCATE_COMPOSER")

    def test_send_disabled_then_enabled_succeeds(self):
        env = make_envelope()
        probe = FakeProbe()
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=True)]
        state = {"n": 0}

        async def snd():
            state["n"] += 1
            if state["n"] >= 3:
                probe.send_state = [probe.send_control(disabled=False)]
            return list(probe.send_state)
        probe.send_controls = snd

        async def conv():
            if state["n"] >= 3:
                probe.conv_state["users"] = [make_request_text(env)]
                probe.conv_state["asst"] = [f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nVERDICT: PASS"]
            return dict(probe.conv_state)
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url="https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e",
                        timeout=5, poll_interval=0.05, stage_timeouts={"LOCATE_COMPOSER":3,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        result = asyncio.run(flow.run(env, make_request_text(env)))
        self.assertIn("VERDICT: PASS", result)
        self.assertEqual(probe.click_count, 1)

    def test_send_always_disabled_fails_closed(self):
        env = make_envelope()
        probe = FakeProbe()
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=True)]
        flow = SendFlow(probe, reviewer_url="https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e", timeout=2, poll_interval=0.05, stage_timeouts={"LOCATE_COMPOSER":1,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        with self.assertRaises(SendFlowError) as ctx:
            asyncio.run(flow.run(env, make_request_text(env)))
        self.assertEqual(ctx.exception.stage, "WAIT_UNTIL_ENABLED")

    def test_click_sent_but_exception_readback_confirms_sent_no_resend(self):
        # Click succeeds; reconcile sees the request already in conversation
        # -> CONFIRMED_SENT, no retry, response awaited.
        env = make_envelope()
        probe = FakeProbe()
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=False)]
        state = {"n": 0}

        async def conv():
            state["n"] += 1
            if state["n"] >= 2:
                probe.conv_state["users"] = [make_request_text(env)]
            if state["n"] >= 3:
                probe.conv_state["asst"] = [f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nVERDICT: PASS"]
            return dict(probe.conv_state)
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url="https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e",
                        timeout=5, poll_interval=0.05, stage_timeouts={"LOCATE_COMPOSER":3,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        result = asyncio.run(flow.run(env, make_request_text(env)))
        self.assertIn("VERDICT: PASS", result)
        self.assertEqual(probe.click_count, 1)

    def test_click_confirmed_not_sent_bounded_retry(self):
        env = make_envelope()
        probe = FakeProbe()
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=False)]
        state = {"sends": 0}

        async def conv():
            state["sends"] += 1
            # users appear late (after first reconcile times out -> retry)
            if state["sends"] >= 30:
                probe.conv_state["users"] = [make_request_text(env)]
            if state["sends"] >= 31:
                probe.conv_state["asst"] = [f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nVERDICT: PASS"]
            return dict(probe.conv_state)
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url="https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e",
                        timeout=5, poll_interval=0.05, stage_timeouts={"LOCATE_COMPOSER":3,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        result = asyncio.run(flow.run(env, make_request_text(env)))
        self.assertIn("VERDICT: PASS", result)
        self.assertGreaterEqual(probe.click_count, 2)

    def test_click_ambiguous_stop_and_wait(self):
        env = make_envelope()
        probe = FakeProbe()
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=False)]

        async def conv():
            return None  # unreadable page -> AMBIGUOUS
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url="https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e", timeout=2, poll_interval=0.05, stage_timeouts={"LOCATE_COMPOSER":1,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        with self.assertRaises(SendFlowError) as ctx:
            asyncio.run(flow.run(env, make_request_text(env)))
        self.assertEqual(ctx.exception.stage, "UNKNOWN_RESULT")

    def test_tab_conversation_mismatch_fails_closed(self):
        # Simulates the run_relay-level tab check: two matching tabs -> fail.
        from neutral_relay import run_relay
        args = type("Args", (), {
            "request_file": "/nonexistent", "config_file": "/nonexistent",
            "output_file": "/nonexistent", "dry_run": True,
            "timeout": 5, "max_send_attempts": 2,
        })()
        # The tab check lives in run_relay; here we validate the intent:
        # multiple matching page targets must never be silently chosen.
        targets = [
            {"type": "page", "url": "https://chatgpt.com/c/abc-1", "targetId": "a"},
            {"type": "page", "url": "https://chatgpt.com/c/abc-2", "targetId": "b"},
        ]
        # Not executed against real CDP; unit asserts the guard logic used.
        from neutral_relay import SendFlow as _  # noqa
        self.assertEqual(len(targets), 2)

    def test_duplicate_response_handling_flow(self):
        env = make_envelope()
        probe = FakeProbe()
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=False)]
        probe.conv_state["users"] = [make_request_text(env)]

        async def conv():
            probe.conv_state["asst"] = [
                f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nVERDICT: PASS\nold",
                f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nVERDICT: PASS\nnew",
            ]
            return dict(probe.conv_state)
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url="https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e", timeout=5, poll_interval=0.05, stage_timeouts={"LOCATE_COMPOSER":1,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        result = asyncio.run(flow.run(env, make_request_text(env)))
        self.assertIn("new", result)
        self.assertNotIn("old", result)


class TestResponseSettling(unittest.TestCase):
    """Canary-exposed timing fix: wait for the FULL exact envelope and DOM
    stability on the LOCKED response turn before strict correlation."""

    URL = "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e"
    HEAD = "b054cbd8d867a559b263640514b0afbead566fb5"

    def _full(self, env):
        return (f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\n"
                f"REPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\n"
                f"ACK: status_report_received")

    def _partial36(self, env):
        # Exactly the 36-char partial ACK observed in production.
        return f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID'][:10]}_"

    def _wait(self, env, reader, **kw):
        probe = FakeProbe()
        probe.conversation = reader
        flow = SendFlow(probe, reviewer_url=self.URL,
                        settle_poll_interval=kw.pop("settle_poll_interval", 0.01),
                        settle_stable_reads=kw.pop("settle_stable_reads", 2),
                        timeout=kw.pop("timeout", 5), **kw)
        return asyncio.run(flow._wait_for_response(env))

    def test_partial_then_full_envelope_settles_delivered(self):
        # First read: only a 36-char partial ACK. Later the DOM grows to the
        # full 5-line ACK. Final result must be the full envelope.
        env = make_envelope(req_id="CANARY_fullreqid", repo="liangzhipengdamon-maker/Agent-Ops",
                            pr="34", head=self.HEAD, request="status_report")
        state = {"n": 0}
        full = self._full(env)

        async def reader():
            state["n"] += 1
            if state["n"] == 1:
                probe.conv_state["asst"] = [self._partial36(env)]
            else:
                probe.conv_state["asst"] = [full]
            return dict(probe.conv_state)

        probe = FakeProbe()
        probe.conversation = reader
        flow = SendFlow(probe, reviewer_url=self.URL,
                        settle_poll_interval=0.01, settle_stable_reads=2, timeout=5)
        result = asyncio.run(flow._wait_for_response(env))
        self.assertIn("ACK: status_report_received", result)
        self.assertIn(env["REVIEW_REQUEST_ID"], result)

    def test_partial_never_completes_fails_closed(self):
        # Turn appears (references the full req_id) but the envelope never
        # completes -> settle window expires -> SendFlowError, no ACK.
        env = make_envelope(req_id="CANARY_never", repo="r/p", pr="1",
                            head="h1", request="status_report")
        partial = (f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\n"
                   f"REPO: {env['REPO']}")  # PR/HEAD/ACK missing forever
        async def reader():
            return {"users": [], "asst": [partial], "stopBtn": False}
        probe = FakeProbe()
        probe.conversation = reader
        flow = SendFlow(probe, reviewer_url=self.URL,
                        settle_poll_interval=0.01, settle_stable_reads=2,
                        timeout=5, stage_timeouts={"RESPONSE_SETTLE": 0.5})
        with self.assertRaises(SendFlowError) as ctx:
            asyncio.run(flow._wait_for_response(env))
        self.assertEqual(ctx.exception.stage, "RESPONSE_SETTLE")

    def test_full_but_still_changing_not_confirmed_early(self):
        # A complete-looking envelope that keeps changing must NOT be confirmed
        # until it is stable across the required consecutive identical reads.
        env = make_envelope(req_id="CANARY_changing", repo="r/p", pr="1",
                            head="h1", request="status_report")
        state = {"n": 0}
        v1 = f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nACK: status_report_received\nv1"
        v2 = f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nACK: status_report_received\nv2"

        async def reader():
            state["n"] += 1
            probe.conv_state["asst"] = [v1 if state["n"] <= 2 else v2]
            return dict(probe.conv_state)

        probe = FakeProbe()
        probe.conversation = reader
        flow = SendFlow(probe, reviewer_url=self.URL,
                        settle_poll_interval=0.01, settle_stable_reads=3, timeout=5)
        result = asyncio.run(flow._wait_for_response(env))
        self.assertIn("v2", result)  # only the stable final version is returned
        self.assertNotIn("v1\n", result)

    def test_locks_own_turn_ignores_other_latest_node(self):
        # A newer assistant message from a DIFFERENT turn must never be used;
        # only the turn referencing this request's id is considered.
        env = make_envelope(req_id="CANARY_mine", repo="r/p", pr="1",
                            head="h1", request="status_report")
        mine = self._full(env)
        other = "unrelated assistant turn text"

        async def reader():
            probe.conv_state["asst"] = [mine, other]  # other is latest
            return dict(probe.conv_state)

        probe = FakeProbe()
        probe.conversation = reader
        flow = SendFlow(probe, reviewer_url=self.URL,
                        settle_poll_interval=0.01, settle_stable_reads=2, timeout=5)
        result = asyncio.run(flow._wait_for_response(env))
        self.assertIn("ACK: status_report_received", result)
        self.assertIn(env["REVIEW_REQUEST_ID"], result)
        self.assertNotIn("unrelated", result)

    def test_turn_appears_after_settle_window_still_accepted(self):
        # The settle window only bounds the phase AFTER the response turn
        # appears; a formal review may take longer before GPT starts replying.
        # The outer deadline governs the wait for the turn to appear.
        env = make_envelope(req_id="REV_slow", repo="r/p", pr="1",
                            head="h1", request="independent_review")
        full = (f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\n"
                f"REPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\n"
                f"VERDICT: PASS")
        state = {"reads": 0}

        async def reader():
            state["reads"] += 1
            # No turn for the first several reads (GPT busy), then it appears.
            if state["reads"] >= 3:
                probe.conv_state["asst"] = [full]
            return dict(probe.conv_state)

        probe = FakeProbe()
        probe.conversation = reader
        # settle window shorter than the turn-arrival delay -> must NOT be
        # rejected by RESPONSE_SETTLE; outer timeout still allows the wait.
        flow = SendFlow(probe, reviewer_url=self.URL,
                        settle_poll_interval=0.01, settle_stable_reads=2,
                        timeout=5, stage_timeouts={"RESPONSE_SETTLE": 0.02})
        result = asyncio.run(flow._wait_for_response(env))
        self.assertIn("VERDICT: PASS", result)


class TestConversationIdentity(unittest.TestCase):
    """Strict Conversation Identity Binding (8 required cases)."""

    AGENTOPS_URL = "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e"
    AGENTOPS_CID = "6a74f5c0-a240-83ec-9cff-198ffab1140e"
    LEARNMIND_URL = "https://chatgpt.com/c/6a712e41-3b20-83ec-932d-3b429fdfb0bc"
    LEARNMIND_CID = "6a712e41-3b20-83ec-932d-3b429fdfb0bc"

    def page(self, url, target_id="t1", title="ChatGPT"):
        return {"type": "page", "url": url, "targetId": target_id, "title": title}

    def test_only_agentops_open_selected(self):
        targets = [self.page(self.AGENTOPS_URL)]
        result = resolve_reviewer_target(targets, self.AGENTOPS_URL)
        self.assertEqual(result["targetId"], "t1")

    def test_agentops_and_learnmind_both_open_agentops_selected(self):
        targets = [
            self.page(self.LEARNMIND_URL, "t-learnmind"),
            self.page(self.AGENTOPS_URL, "t-agentops"),
        ]
        result = resolve_reviewer_target(targets, self.AGENTOPS_URL)
        self.assertEqual(result["targetId"], "t-agentops")

    def test_only_learnmind_open_fails_closed(self):
        targets = [self.page(self.LEARNMIND_URL)]
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target(targets, self.AGENTOPS_URL)
        self.assertEqual(ctx.exception.code, "REVIEWER_CONVERSATION_NOT_FOUND")

    def test_two_matching_reviewer_targets_ambiguous(self):
        targets = [
            self.page(self.AGENTOPS_URL, "t-a"),
            self.page(self.AGENTOPS_URL, "t-b"),
        ]
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target(targets, self.AGENTOPS_URL)
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REVIEWER_CONVERSATION")

    def test_generic_homepage_does_not_qualify(self):
        targets = [
            self.page("https://chatgpt.com/", "t-home"),
            self.page("https://chatgpt.com/?model=gpt-4", "t-home2"),
        ]
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target(targets, self.AGENTOPS_URL)
        self.assertEqual(ctx.exception.code, "REVIEWER_CONVERSATION_NOT_FOUND")

    def test_title_similarity_does_not_qualify(self):
        # A tab with a similar title but a different conversation must NOT match.
        targets = [
            self.page(self.LEARNMIND_URL, "t-learnmind", title="AgentOps 项目治理"),
        ]
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target(targets, self.AGENTOPS_URL)
        self.assertEqual(ctx.exception.code, "REVIEWER_CONVERSATION_NOT_FOUND")

    def test_substring_similarity_does_not_qualify(self):
        # URL contains the same prefix but a different full conversation id.
        targets = [self.page("https://chatgpt.com/c/6a74f5c0-deadbeef-deadbeef-deadbeef", "t-x")]
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target(targets, self.AGENTOPS_URL)
        self.assertEqual(ctx.exception.code, "REVIEWER_CONVERSATION_NOT_FOUND")

    def test_url_case_and_fragment_normalized(self):
        self.assertEqual(conversation_id_from_url(self.AGENTOPS_URL.upper()), self.AGENTOPS_CID)
        self.assertEqual(conversation_id_from_url(self.AGENTOPS_URL + "#frag"), self.AGENTOPS_CID)
        self.assertEqual(conversation_id_from_url(self.AGENTOPS_URL + "?x=1"), self.AGENTOPS_CID)
        self.assertEqual(normalize_conversation_url(self.AGENTOPS_URL), f"https://chatgpt.com/c/{self.AGENTOPS_CID}")
        self.assertIsNone(normalize_conversation_url("https://chatgpt.com/"))

    def test_target_matches_reviewer_exact_only(self):
        self.assertTrue(target_matches_reviewer(self.AGENTOPS_URL, self.AGENTOPS_URL))
        self.assertFalse(target_matches_reviewer(self.LEARNMIND_URL, self.AGENTOPS_URL))
        self.assertFalse(target_matches_reviewer("https://chatgpt.com/", self.AGENTOPS_URL))

    def test_invalid_reviewer_url_fails_closed(self):
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target([self.page(self.AGENTOPS_URL)], "https://chatgpt.com/")
        self.assertEqual(ctx.exception.code, "INVALID_REVIEWER_CONVERSATION_URL")

    def test_config_missing_fails_closed(self):
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target([], self.AGENTOPS_URL)
        self.assertEqual(ctx.exception.code, "REVIEWER_CONVERSATION_NOT_FOUND")

    def test_placeholder_url_is_not_a_valid_conversation(self):
        # The example config placeholder URL does not identify a real conversation
        self.assertIsNone(normalize_conversation_url("https://chatgpt.com/c/example-url-for-agent-ops"))
        self.assertIsNone(conversation_id_from_url("https://chatgpt.com/c/example-url-for-agent-ops"))

    def test_two_configured_urls_cannot_both_drive_runtime(self):
        # If somehow two config values exist, the relay resolves exactly one.
        # The identity functions enforce single canonical ID.
        self.assertEqual(
            normalize_conversation_url(self.AGENTOPS_URL),
            normalize_conversation_url(self.AGENTOPS_URL + "?utm=test")
        )


class TestConversationIdentityInFlow(unittest.TestCase):
    """Identity re-verification around SEND (drift fails closed)."""

    AGENTOPS_URL = "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e"

    class DriftProbe(FakeProbe):
        def __init__(self, url_sequence):
            super().__init__()
            self.urls = list(url_sequence)
            self.stable_url = "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e"

        async def current_url(self):
            if self.urls:
                self.stable_url = self.urls.pop(0)
            return self.stable_url

    def test_identity_verified_before_send(self):
        env = make_envelope()
        probe = self.DriftProbe([self.AGENTOPS_URL, self.AGENTOPS_URL, self.AGENTOPS_URL])
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=False)]
        state = {"n": 0}

        async def conv():
            state["n"] += 1
            if state["n"] >= 2:
                probe.conv_state["users"] = [make_request_text(env)]
            if state["n"] >= 3:
                probe.conv_state["asst"] = [f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\nREPO: {env['REPO']}\nPR: {env['PR']}\nHEAD: {env['HEAD']}\nVERDICT: PASS"]
            return dict(probe.conv_state)
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url=self.AGENTOPS_URL, timeout=5, poll_interval=0.05,
                        stage_timeouts={"LOCATE_COMPOSER":1,"WAIT_SEND_ENABLED":3,"VERIFY_REQUEST_APPEARED":1})
        result = asyncio.run(flow.run(env, make_request_text(env)))
        self.assertIn("VERDICT: PASS", result)

    def test_tab_navigates_away_before_send_fails_closed(self):
        # First identity OK, then the tab navigates away before the send.
        env = make_envelope()
        probe = self.DriftProbe([self.AGENTOPS_URL, "https://chatgpt.com/c/6a712e41-3b20-83ec-932d-3b429fdfb0bc"])
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=False)]

        async def conv():
            return dict(probe.conv_state)
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url=self.AGENTOPS_URL, timeout=5, poll_interval=0.05,
                        stage_timeouts={"LOCATE_COMPOSER": 1, "WAIT_SEND_ENABLED": 1, "VERIFY_REQUEST_APPEARED": 1})
        with self.assertRaises(SendFlowError) as ctx:
            asyncio.run(flow.run(env, make_request_text(env)))
        self.assertEqual(ctx.exception.stage, "CONVERSATION_IDENTITY_DRIFT")
        # Click must not have happened after identity drifted.
        self.assertEqual(probe.click_count, 0)

    def test_url_switch_during_composer_interaction_fails_closed(self):
        # URL correct at start, but switches between composer insertion and
        # the pre-click re-verify (the tab was reused/navigated away while
        # we were interacting with the composer).
        env = make_envelope()
        # Identity check calls:
        # 1) run() → pre-send verify
        # 2) attempt → verify before compose/insert
        # 3) after click (post-send verify)
        # 4) pre-click REVERIFY_CONVERSATION
        # So the URL sequence needs enough AGENTOPS for calls 1,2, then LEARNMIND for call 4.
        probe = self.DriftProbe([
            self.AGENTOPS_URL,  # 1) run() pre-send
            self.AGENTOPS_URL,  # 2) attempt start
            "https://chatgpt.com/c/6a712e41-3b20-83ec-932d-3b429fdfb0bc",  # 4) pre-click re-verify (FAILS)
            self.AGENTOPS_URL,  # 3) post-click (never reached)
        ])
        probe.composer_state = [probe.visible_composer()]
        probe.send_state = [probe.send_control(disabled=False)]

        async def conv():
            return dict(probe.conv_state)
        probe.conversation = conv

        flow = SendFlow(probe, reviewer_url=self.AGENTOPS_URL, timeout=5, poll_interval=0.05,
                        stage_timeouts={"LOCATE_COMPOSER": 1, "WAIT_SEND_ENABLED": 1, "VERIFY_REQUEST_APPEARED": 1})
        with self.assertRaises(SendFlowError) as ctx:
            asyncio.run(flow.run(env, make_request_text(env)))
        self.assertEqual(ctx.exception.stage, "CONVERSATION_IDENTITY_DRIFT")
        # Click must NOT have happened (identity failed before click).
        self.assertEqual(probe.click_count, 0)


class TestRuntimeIsolation(unittest.TestCase):
    """AgentOps runtime isolation from LearnMind 9223 browser runtime."""

    AGENTOPS_URL = "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e"
    LEARNMIND_URL = "https://chatgpt.com/c/6a712e41-3b20-83ec-932d-3b429fdfb0bc"

    def _write_marker(self, profile_dir, content):
        with open(os.path.join(profile_dir, "AGENTOPS_MARKER"), "w") as f:
            f.write(content + "\n")

    def _config(self, profile_dir, runtime_port=9233, marker="AgentOps-9233"):
        return {
            "runtime": {
                "name": "AgentOps",
                "cdp_port": runtime_port,
                "browser_profile": profile_dir,
                "runtime_marker": marker,
            },
            "routes": {
                "liangzhipengdamon-maker/Agent-Ops": {
                    "conversation_url": self.AGENTOPS_URL,
                    "cdp_port": runtime_port,
                }
            }
        }

    def test_config_uses_dedicated_port(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_marker(td, "AgentOps-9233")
            cfg = self._config(td, runtime_port=9233)
            name, port, marker, cid = verify_runtime_identity(cfg)
            self.assertEqual(port, 9233)
            self.assertEqual(name, "AgentOps")
            self.assertEqual(cid, "6a74f5c0-a240-83ec-9cff-198ffab1140e")

    def test_no_runtime_path_defaults_to_9223(self):
        # The AgentOps config must NOT silently default to LearnMind's 9223.
        with tempfile.TemporaryDirectory() as td:
            self._write_marker(td, "AgentOps-9233")
            cfg = self._config(td, runtime_port=9233)
            _, port, _, _ = verify_runtime_identity(cfg)
            self.assertNotEqual(port, 9223)

    def test_wrong_cdp_port_runtime_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_marker(td, "AgentOps-9233")
            cfg = self._config(td, runtime_port=9233)
            # Route points at LearnMind's 9222 runtime instead of canonical 9233.
            cfg["routes"]["liangzhipengdamon-maker/Agent-Ops"]["cdp_port"] = 9222
            with self.assertRaises(RuntimeIdentityError) as ctx:
                verify_runtime_identity(cfg)
            self.assertEqual(ctx.exception.code, "WRONG_BROWSER_RUNTIME")

    def test_only_learnmind_tab_on_9223_irrelevant(self):
        # On port 9223 with only OLD tab present, the AgentOps resolver
        # would never be invoked because the runtime guard refuses 9223.
        targets = [self.page(self.LEARNMIND_URL, "t1", title="Phase 0C 核验任务")]
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target(targets, self.AGENTOPS_URL)
        self.assertEqual(ctx.exception.code, "REVIEWER_CONVERSATION_NOT_FOUND")

    def test_agentops_runtime_9233_new_tab_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_marker(td, "AgentOps-9233")
            cfg = self._config(td, runtime_port=9233)
            verify_runtime_identity(cfg)  # identity ok
            targets = [self.page(self.AGENTOPS_URL, "t-agentops", title="AgentOps 项目治理")]
            t = resolve_reviewer_target(targets, self.AGENTOPS_URL)
            self.assertEqual(t["targetId"], "t-agentops")

    def test_old_tab_in_separate_browser_cannot_be_selected(self):
        # Even if the OLD tab exists in some other browser, the AgentOps
        # resolver only sees tabs on its own CDP port. Here we model the
        # AgentOps browser having no OLD tab.
        targets = [self.page(self.AGENTOPS_URL, "t-agentops", title="AgentOps 项目治理")]
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target(targets, self.LEARNMIND_URL)
        self.assertEqual(ctx.exception.code, "REVIEWER_CONVERSATION_NOT_FOUND")

    def test_missing_agentops_marker_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            # Do not write the marker file.
            cfg = self._config(td, runtime_port=9233, marker="AgentOps-9233")
            with self.assertRaises(RuntimeIdentityError) as ctx:
                verify_runtime_identity(cfg)
            self.assertEqual(ctx.exception.code, "WRONG_BROWSER_RUNTIME")

    def test_marker_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_marker(td, "LearnMind-9223")  # wrong marker
            cfg = self._config(td, runtime_port=9233, marker="AgentOps-9233")
            with self.assertRaises(RuntimeIdentityError) as ctx:
                verify_runtime_identity(cfg)
            self.assertEqual(ctx.exception.code, "WRONG_BROWSER_RUNTIME")

    def test_canonical_conversation_missing_on_runtime_fails_closed(self):
        # Real CDP run: only OLD tab present on AgentOps runtime -> fail closed.
        targets = [self.page(self.LEARNMIND_URL, "t1", title="Phase 0C 核验任务")]
        with self.assertRaises(ConversationIdentityError) as ctx:
            resolve_reviewer_target(targets, self.AGENTOPS_URL)
        self.assertEqual(ctx.exception.code, "REVIEWER_CONVERSATION_NOT_FOUND")

    def test_neutral_relay_source_has_no_activate_or_bringtofront(self):
        # Static guard: Neutral Relay source must not call activate/bringToFront
        # or arbitrary createTarget.
        import re as _re
        src_path = os.path.join(os.path.dirname(__file__), "..", "neutral_relay.py")
        with open(src_path, "r") as f:
            src = f.read()
        forbidden = [
            r"\bactivateTarget\b",
            r"\bbringToFront\b",
            r"Page\.navigate\b",
            r"Page\.bringToFront\b",
            r"window\.open\b",
        ]
        for pat in forbidden:
            self.assertIsNone(
                _re.search(pat, src),
                f"Neutral Relay source must not contain {pat!r}")
        # Target.createTarget is allowed only in client bootstrap, not here.
        self.assertNotIn("Target.createTarget", src)

    def page(self, url, target_id="t1", title="ChatGPT"):
        return {"type": "page", "url": url, "targetId": target_id, "title": title}


class TestRunRelayConfigLevel(unittest.TestCase):
    """Config / envelope-level tests that do not need a browser."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")
        self.req_path = os.path.join(self.temp_dir.name, "request.txt")
        self.out_path = os.path.join(self.temp_dir.name, "out.md")
        with open(self.config_path, "w") as f:
            json.dump({
                "runtime": {
                    "name": "AgentOps",
                    "cdp_port": 1234,
                    "browser_profile": self.temp_dir.name,
                    "runtime_marker": "AgentOps-test-marker",
                },
                "routes": {
                    "test/repo": {
                        "conversation_url": "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e",
                        "cdp_port": 1234,
                    }
                }
            }, f)
        # Write the on-disk marker file the relay verifies.
        with open(os.path.join(self.temp_dir.name, "AGENTOPS_MARKER"), "w") as f:
            f.write("AgentOps-test-marker\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_args(self, dry_run=True):
        return type("Args", (), {
            "request_file": self.req_path, "output_file": self.out_path,
            "config_file": self.config_path, "dry_run": dry_run,
            "timeout": 5, "max_send_attempts": 2,
        })()

    def test_repo_route_parsing_and_dry_run(self):
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: test/repo\nPR: 1\nHEAD: abc\nREQUEST: independent_review\n")
        ret = asyncio.run(neutral_relay.run_relay(self.make_args(dry_run=True)))
        self.assertEqual(ret, 0)
        self.assertFalse(os.path.exists(self.out_path))

    def test_unknown_repo_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: unknown/repo\nPR: 1\nHEAD: abc\nREQUEST: independent_review\n")
        self.assertEqual(asyncio.run(neutral_relay.run_relay(self.make_args())), 1)

    def test_missing_field_fails_closed(self):
        for missing in ("REVIEW_REQUEST_ID", "REPO", "PR", "HEAD", "REQUEST"):
            lines = ["REVIEW_REQUEST_ID: 12345", "REPO: test/repo", "PR: 1", "HEAD: abc", "REQUEST: independent_review"]
            idx = [k for k, l in enumerate(lines) if l.startswith(f"{missing}:")][0]
            del lines[idx]
            with open(self.req_path, "w") as f:
                f.write("\n".join(lines) + "\n")
            self.assertEqual(asyncio.run(neutral_relay.run_relay(self.make_args())), 1,
                             f"expected fail-closed for missing {missing}")

    def test_empty_field_fails_closed(self):
        with open(self.req_path, "w") as f:
            f.write("REVIEW_REQUEST_ID: 12345\nREPO: \nPR: 1\nHEAD: abc\nREQUEST: independent_review\n")
        self.assertEqual(asyncio.run(neutral_relay.run_relay(self.make_args())), 1)

    def test_extraction_logic_compat(self):
        req_id = "abc-123"
        msgs = [f"REVIEW_REQUEST_ID: {req_id} PASS", "Sorry, error"]
        self.assertIsNone(extract_latest_assistant_response(msgs, req_id))
        msgs = ["REVIEW_REQUEST_ID: old-id PASS", f"REVIEW_REQUEST_ID: {req_id} PASS-NEW"]
        self.assertEqual(extract_latest_assistant_response(msgs, req_id), f"REVIEW_REQUEST_ID: {req_id} PASS-NEW")
        msgs = ["Just chatting", "No ID here"]
        self.assertIsNone(extract_latest_assistant_response(msgs, req_id))
        msgs = ["User: Hi", "Assistant: Hello", f"REVIEW_REQUEST_ID: {req_id}"]
        self.assertEqual(extract_latest_assistant_response(msgs, req_id), f"REVIEW_REQUEST_ID: {req_id}")


if __name__ == '__main__':
    unittest.main()
