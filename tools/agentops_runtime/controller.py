#!/usr/bin/env python3
"""Thin AUTO/MANUAL Controller/Watcher (AGE-30).

Keeps the task loop alive across Builder exits and waiting periods. It has
no parallel state kernel: durable state is written to LoopX (refresh-state)
via runtime_loop; Builder handoff uses the existing `.agent-bridge` wake
files. Terminates only on accepted completion, PR closure, or task
closure/cancellation.
"""

import os
import time

from .runtime_loop import decide, _pr_state
from . import linear_adapter


class ControlWatcher:
    def __init__(self, task_id: str, repo: str, pr: str,
                 interval: int = 600):
        self.task_id = task_id
        self.repo = repo
        self.pr = str(pr)
        self.interval = max(int(interval), 5)

    def _terminal(self) -> bool:
        gh = _pr_state(self.repo, int(self.pr))
        if gh is not None and gh.get("state") in ("MERGED", "CLOSED"):
            print(f"WATCHER_TERMINAL: PR {self.pr} {gh.get('state')}")
            return True
        lin = linear_adapter.read_linear_issue(self.task_id)
        if lin and (lin.get("state_type") in ("canceled", "completed")
                    or lin.get("state_name") in ("Canceled", "Done")):
            print(f"WATCHER_TERMINAL: Linear task {self.task_id} "
                  f"{lin.get('state_name')}")
            return True
        return False  # unreadable/unknown -> keep retrying, never terminal

    def run_forever(self) -> bool:
        print(f"WATCHER_STARTED: task={self.task_id} pr={self.pr} "
              f"interval={self.interval}s")
        try:
            while True:
                time.sleep(self.interval)
                if self._terminal():
                    break
                outcome = decide(self.task_id, self.repo, self.pr)
                phase = outcome.get("phase")
                print(f"WATCHER_STEP: phase={phase} "
                      f"review={outcome.get('review_decision')}")
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
