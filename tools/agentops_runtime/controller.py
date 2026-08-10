#!/usr/bin/env python3
"""Thin AUTO/MANUAL Controller/Watcher (AGE-30 / AGE-45).

Keeps the task loop alive across Builder exits and waiting periods. It has
no parallel state kernel: durable state is written to LoopX (refresh-state)
via runtime_loop; Builder handoff uses the existing `.agent-bridge` wake
files.

AGE-45 invariant: remote PR lifecycle is never interpreted as terminal by a
Watcher-side shortcut before the canonical runtime decision step has applied
the gate-independent lifecycle guard. CLOSED/MERGED therefore flows through
`decide()` first; only a returned TERMINAL is accepted as terminal.
"""

import time

from .runtime_loop import decide


class ControlWatcher:
    def __init__(self, task_id: str, repo: str, pr: str,
                 interval: int = 600):
        self.task_id = task_id
        self.repo = repo
        self.pr = str(pr)
        self.interval = max(int(interval), 5)

    def _terminal(self) -> bool:
        """Compatibility helper with no independent lifecycle authority.

        The watcher must not inspect PR state/gate files here. The canonical
        `decide()` result is the only terminal decision source used by
        `run_forever()`. Keeping this helper false makes legacy callers fail
        closed rather than recreating the old gate-evidence bypass.
        """
        return False

    def run_forever(self) -> bool:
        print(f"WATCHER_STARTED: task={self.task_id} pr={self.pr} "
              f"interval={self.interval}s")
        try:
            while True:
                time.sleep(self.interval)

                # AGE-45 P0 remediation: DECIDE FIRST. Any remote CLOSED/MERGED
                # state is evaluated by runtime_loop.decide(), whose active
                # MANUAL guard is gate-independent and requires exact signed
                # action-specific PO authorization before allowing TERMINAL.
                outcome = decide(self.task_id, self.repo, self.pr)
                phase = outcome.get("phase")
                review_decision = outcome.get("review_decision")
                print(f"WATCHER_STEP: phase={phase} "
                      f"review={review_decision}")

                violation = outcome.get("lifecycle_violation")
                if review_decision == "LIFECYCLE_VIOLATION" or violation:
                    action = (violation or {}).get("action")
                    print("WATCHER_WAITING_PO_AFTER_LIFECYCLE_VIOLATION: "
                          f"pr={self.pr} action={action}")
                    continue

                # P1-1: LoopX degradation is observable, never silent.
                loopx = outcome.get("loopx") or {}
                if loopx.get("ok") is False:
                    print(f"WATCHER_LOOPX_DEGRADED: {loopx.get('detail')}")
                builder = outcome.get("builder") or {}
                if builder.get("ok") is False:
                    print(f"WATCHER_BUILDER_HANDOFF_FAILED: "
                          f"detail={builder.get('detail')} "
                          f"reason={builder.get('reason')}")
                gate = outcome.get("gate_report") or {}
                if gate.get("sent") and not gate.get("delivered"):
                    print(f"WATCHER_GATE_REPORT_FAILED: "
                          f"delivered={gate.get('delivered')} "
                          f"corr={gate.get('correlation_id')}")

                if phase in ("COMPLETE", "TERMINAL"):
                    print(f"WATCHER_EXIT: {phase}")
                    break
        finally:
            pass
        return True
