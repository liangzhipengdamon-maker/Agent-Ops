import asyncio
import os
import sys
import unittest

# Keep the test isolated to the neutral-relay transport module.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from neutral_relay import SendFlow, SendFlowError


URL = "https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e"


def make_envelope(req_id="AGE51-stream"):
    return {
        "REVIEW_REQUEST_ID": req_id,
        "REPO": "test/repo",
        "PR": "51",
        "HEAD": "abc123",
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


class StreamingProbe:
    """Scripted assistant-turn probe with an explicit ChatGPT busy signal."""

    def __init__(self, states):
        self.states = list(states)
        self.index = 0
        self.reads = 0

    async def current_url(self):
        return URL

    async def assistant_turns(self):
        self.reads += 1
        if self.index < len(self.states) - 1:
            state = self.states[self.index]
            self.index += 1
        else:
            state = self.states[-1]
        return [{
            "text": state["text"],
            "id": "turn-age51",
            "stopBtn": state["stopBtn"],
        }]


class TestAge51StreamingCompleteness(unittest.TestCase):
    def test_stable_complete_envelope_is_not_accepted_while_still_streaming(self):
        env = make_envelope()
        partial = response_text(env, "partial body")
        final = response_text(env, "partial body\nFINAL_TAIL: complete")
        # The partial text is envelope-complete and repeats longer than the
        # normal settle threshold, but ChatGPT is still generating. The relay
        # must wait through that stable pause, observe later growth, then only
        # settle after the busy signal disappears.
        states = [
            {"text": partial, "stopBtn": True},
            {"text": partial, "stopBtn": True},
            {"text": partial, "stopBtn": True},
            {"text": partial, "stopBtn": True},
            {"text": final, "stopBtn": True},
            {"text": final, "stopBtn": False},
            {"text": final, "stopBtn": False},
            {"text": final, "stopBtn": False},
        ]
        probe = StreamingProbe(states)
        flow = SendFlow(
            probe,
            reviewer_url=URL,
            timeout=1,
            settle_poll_interval=0.001,
            settle_stable_reads=3,
            stage_timeouts={"RESPONSE_SETTLE": 0.2},
        )
        result = asyncio.run(flow._wait_for_response(env))
        self.assertIn("FINAL_TAIL: complete", result)
        self.assertGreaterEqual(probe.reads, 8)

    def test_busy_signal_that_never_clears_fails_closed_at_outer_timeout(self):
        env = make_envelope(req_id="AGE51-timeout")
        complete = response_text(env, "complete-looking but still streaming")
        probe = StreamingProbe([{"text": complete, "stopBtn": True}])
        flow = SendFlow(
            probe,
            reviewer_url=URL,
            timeout=0.03,
            settle_poll_interval=0.005,
            settle_stable_reads=2,
            stage_timeouts={"RESPONSE_SETTLE": 0.01},
        )
        with self.assertRaises(SendFlowError) as ctx:
            asyncio.run(flow._wait_for_response(env))
        self.assertEqual(ctx.exception.stage, "WAIT_ASSISTANT_RESPONSE")


if __name__ == "__main__":
    unittest.main()
