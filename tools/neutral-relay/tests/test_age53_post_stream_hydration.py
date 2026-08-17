import asyncio
import os
import sys
import unittest

# Keep the test isolated to the neutral-relay transport module.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from neutral_relay import SendFlow, SendFlowError


URL = "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e"


def make_envelope(req_id="AGE53-stream"):
    return {
        "REVIEW_REQUEST_ID": req_id,
        "REPO": "test/repo",
        "PR": "53",
        "HEAD": "deadbeef",
        "REQUEST": "independent_review",
    }


def response_text(env, tail):
    return (
        f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\n"
        f"REPO: {env['REPO']}\n"
        f"PR: {env['PR']}\n"
        f"HEAD: {env['HEAD']}\n"
        "RESULT: PASS\n"
        f"SUMMARY:\n{tail}"
    )


class ScriptedProbe:
    """Deterministic assistant-turn probe.

    The script is a list of states; each state is either a single turn dict or
    a list of turn dicts to return on that read. When the script runs out, the
    last state is repeated forever. ``id`` controls the locked-node identity.
    """

    def __init__(self, script):
        self.script = list(script)
        self.reads = 0
        self.last_text = None

    async def current_url(self):
        return URL

    async def assistant_turns(self):
        self.reads += 1
        if len(self.script) > 1:
            state = self.script.pop(0)
        else:
            state = self.script[0]
        turns = state if isinstance(state, list) else [state]
        if turns:
            self.last_text = turns[-1].get("text")
        return turns


class TestAge53PostStreamHydration(unittest.TestCase):

    def _flow(self, env, probe, settle_stable_reads=3, response_settle=0.5,
              timeout=5.0, poll=0.002):
        return SendFlow(
            probe,
            reviewer_url=URL,
            timeout=timeout,
            settle_poll_interval=poll,
            settle_stable_reads=settle_stable_reads,
            stage_timeouts={"RESPONSE_SETTLE": response_settle},
        )

    def test_a_age51_protection_retained(self):
        # Complete envelope + byte-identical text repeated many times while
        # stopBtn=true must NEVER return. Only after busy=false may the
        # post-stream completion path run.
        env = make_envelope()
        complete = response_text(env, "complete body")
        script = [
            {"text": complete, "id": "turn-0", "stopBtn": True},
            {"text": complete, "id": "turn-0", "stopBtn": True},
            {"text": complete, "id": "turn-0", "stopBtn": True},
            {"text": complete, "id": "turn-0", "stopBtn": True},
            {"text": complete, "id": "turn-0", "stopBtn": True},
            {"text": complete, "id": "turn-0", "stopBtn": False},
            {"text": complete, "id": "turn-0", "stopBtn": False},
            {"text": complete, "id": "turn-0", "stopBtn": False},
        ]
        probe = ScriptedProbe(script)
        flow = self._flow(env, probe)
        result = asyncio.run(flow._wait_for_response(env))
        self.assertIn("complete body", result)
        # It waited through the stable-but-streaming prefix AND the settle reads.
        self.assertGreaterEqual(probe.reads, 8)

    def test_b_always_hydrating_returns_last_valid_snapshot(self):
        # stopBtn=false and each snapshot is complete + strictly correlated,
        # but innerText changes on EVERY read for the whole settle window, so
        # byte-for-byte stability is never reached. The deadline fallback must
        # return the latest valid snapshot instead of failing RESPONSE_SETTLE.
        env = make_envelope(req_id="AGE53-B")
        script = [
            {"text": response_text(env, f"hydrating version {i}"),
             "id": "turn-0", "stopBtn": False}
            for i in range(1, 200)
        ]
        probe = ScriptedProbe(script)
        flow = self._flow(env, probe, settle_stable_reads=3, response_settle=0.05,
                          timeout=5.0, poll=0.002)
        result = asyncio.run(flow._wait_for_response(env))
        # The deadline fired long before the 200-snapshot script was exhausted,
        # so the last snapshot read must be the returned one.
        self.assertEqual(result, probe.last_text)
        self.assertIn("hydrating version", result)
        # It must NOT be the very first snapshot.
        self.assertNotIn("version 1\n", result)

    def test_c_latest_not_stale(self):
        # A, B, C are all complete + correlated. The timeout fallback must
        # return C (the latest), never A or B.
        env = make_envelope(req_id="AGE53-C")
        a = response_text(env, "alpha version")
        b = response_text(env, "beta version")
        c = response_text(env, "gamma final")
        script = [
            {"text": a, "id": "turn-0", "stopBtn": False},
            {"text": b, "id": "turn-0", "stopBtn": False},
            {"text": c, "id": "turn-0", "stopBtn": False},
        ]
        # Repeat C forever so the settle window expires with C as the latest
        # valid snapshot (stability threshold is high enough to not fire first).
        probe = ScriptedProbe(script)
        flow = self._flow(env, probe, settle_stable_reads=50, response_settle=0.02,
                          timeout=5.0, poll=0.002)
        result = asyncio.run(flow._wait_for_response(env))
        self.assertIn("gamma final", result)
        self.assertNotIn("alpha version", result)
        self.assertNotIn("beta version", result)

    def test_d_stabilizes_early_before_deadline(self):
        # Post-stream DOM settles naturally before the deadline: the relay must
        # return via the normal stable-reads early-settle path, not wait the
        # full RESPONSE_SETTLE window.
        env = make_envelope(req_id="AGE53-D")
        a = response_text(env, "draft one")
        b = response_text(env, "draft two")
        final = response_text(env, "settled final")
        script = [
            {"text": a, "id": "turn-0", "stopBtn": False},
            {"text": b, "id": "turn-0", "stopBtn": False},
            {"text": final, "id": "turn-0", "stopBtn": False},
            {"text": final, "id": "turn-0", "stopBtn": False},
            {"text": final, "id": "turn-0", "stopBtn": False},
        ]
        probe = ScriptedProbe(script)
        flow = self._flow(env, probe, settle_stable_reads=3, response_settle=5.0,
                          timeout=5.0, poll=0.002)
        result = asyncio.run(flow._wait_for_response(env))
        self.assertIn("settled final", result)
        # Early settle: far fewer reads than a full 5s window would take.
        self.assertLess(probe.reads, 10)

    def test_e_streaming_resume_invalidates_old_snapshot(self):
        # stopBtn=false valid snapshot A -> stopBtn=true (streaming resumes) ->
        # A must be invalidated -> text grows -> stopBtn=false -> fresh
        # post-stream window. The relay must never return the old A.
        env = make_envelope(req_id="AGE53-E")
        a = response_text(env, "old snapshot")
        growing = response_text(env, "still growing")
        final = response_text(env, "resumed final")
        script = [
            {"text": a, "id": "turn-0", "stopBtn": False},
            {"text": a, "id": "turn-0", "stopBtn": True},
            {"text": growing, "id": "turn-0", "stopBtn": True},
            {"text": growing, "id": "turn-0", "stopBtn": True},
            {"text": final, "id": "turn-0", "stopBtn": False},
            {"text": final, "id": "turn-0", "stopBtn": False},
            {"text": final, "id": "turn-0", "stopBtn": False},
        ]
        probe = ScriptedProbe(script)
        flow = self._flow(env, probe, settle_stable_reads=3, response_settle=0.5,
                          timeout=5.0, poll=0.002)
        result = asyncio.run(flow._wait_for_response(env))
        self.assertIn("resumed final", result)
        self.assertNotIn("old snapshot", result)

    def test_f_no_valid_snapshot_fails_closed(self):
        # stopBtn=false until the settle deadline, but the envelope is never
        # complete / strict correlation always fails -> FAIL CLOSED.
        env = make_envelope(req_id="AGE53-F")
        broken = (f"REVIEW_REQUEST_ID: {env['REVIEW_REQUEST_ID']}\n"
                  f"REPO: {env['REPO']}\n"
                  "PR: 999\n"
                  "HEAD: WRONG")  # HEAD mismatches the envelope
        script = [{"text": broken, "id": "turn-0", "stopBtn": False}]
        probe = ScriptedProbe(script)
        flow = self._flow(env, probe, settle_stable_reads=3, response_settle=0.03,
                          timeout=5.0, poll=0.002)
        with self.assertRaises(SendFlowError) as ctx:
            asyncio.run(flow._wait_for_response(env))
        self.assertEqual(ctx.exception.stage, "RESPONSE_SETTLE")

    def test_g_locked_node_disappears_fails_closed(self):
        # After the response turn is locked, its stable node identity vanishes
        # (replaced by a different node id) -> FAIL CLOSED.
        env = make_envelope(req_id="AGE53-G")
        text = response_text(env, "node body")
        script = [
            {"text": text, "id": "turn-0", "stopBtn": False},
            {"text": text, "id": "turn-1", "stopBtn": False},
        ]
        probe = ScriptedProbe(script)
        flow = self._flow(env, probe, settle_stable_reads=3, response_settle=0.5,
                          timeout=5.0, poll=0.002)
        with self.assertRaises(SendFlowError) as ctx:
            asyncio.run(flow._wait_for_response(env))
        self.assertEqual(ctx.exception.stage, "RESPONSE_SETTLE")
        self.assertIn("vanished", ctx.exception.reason)


if __name__ == "__main__":
    unittest.main()
