#!/usr/bin/env python3
"""AGE-30 Controller/Watcher.

Keeps the AUTO/MANUAL task loop alive across Builder exits and waiting
periods. The Controller terminates only on accepted completion, closure,
or cancellation. A closed/merged PR or canceled task stops the watcher
cleanly (no residual completion-report spam).

MANUAL: Builder may idle/exit; the watcher stays alive at WAITING_PO_AUTH
until the PO decision arrives.
"""

import dataclasses
import json
import os
import subprocess
import time
from typing import Optional

from .runtime_loop import RuntimeLoop, _pr_state


@dataclasses.dataclass
class WatcherState:
    task_id: str
    repo: str
    pr: str
    pid: int
    started_at: str
    last_phase: str
    last_review: str
    terminated: bool = False

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WatcherState":
        return cls(**d)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


class ControlWatcher:
    def __init__(self, task_id: str, repo: str, pr: str, state_dir: str,
                 interval: int = 600, loop: Optional[RuntimeLoop] = None,
                 loopx_bin: Optional[str] = None):
        self.task_id = task_id
        self.repo = repo
        self.pr = str(pr)
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self.interval = max(int(interval), 5)
        self.state_path = os.path.join(state_dir, f"watcher_{task_id}.json")
        self.loop = loop
        self.loopx_bin = loopx_bin or os.path.expanduser("~/.local/bin/loopx-canary")

    # P0-5: durable state goes through LoopX (the existing runtime state
    # kernel), not a parallel JSON/PID kernel. The local watcher file is only
    # the PID/claim bookkeeping needed for the single-instance guard; the
    # authoritative loop state is written to LoopX via refresh-state.
    def _loopx_refresh(self, phase: str, review: str):
        try:
            subprocess.run(
                [self.loopx_bin, "refresh-state", "--goal-id", self.task_id,
                 "--project", ".", "--classification", "agentops_watcher",
                 "--next-action", phase, "--agent-id", f"agent-{self.pr}"],
                capture_output=True, text=True, timeout=30)
        except Exception:
            pass  # LoopX unavailable: still guard via local PID file

    def _load(self) -> Optional[WatcherState]:
        if not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path) as f:
                return WatcherState.from_dict(json.load(f))
        except Exception:
            return None

    def _save(self, ws: WatcherState):
        with open(self.state_path, "w") as f:
            json.dump(ws.to_dict(), f, indent=2, ensure_ascii=False)

    def acquire(self) -> bool:
        existing = self._load()
        if existing and _pid_alive(existing.pid):
            print(f"WATCHER_DUPLICATE: task {self.task_id} watched by pid "
                  f"{existing.pid}")
            return False
        self._save(WatcherState(
            task_id=self.task_id, repo=self.repo, pr=self.pr, pid=os.getpid(),
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            last_phase="INTAKE", last_review=""))
        self._loopx_refresh("INTAKE", "")
        return True

    def release(self):
        try:
            if os.path.exists(self.state_path):
                os.remove(self.state_path)
        except OSError:
            pass

    def _terminal(self) -> bool:
        gh = _pr_state(self.repo, int(self.pr))
        if gh is None:
            return False  # keep trying on transient read failure
        if gh.get("state") in ("MERGED", "CLOSED"):
            print(f"WATCHER_TERMINAL: PR {self.pr} {gh.get('state')}")
            return True
        return False

    def run_forever(self, step_fn, interval_override: Optional[int] = None) -> bool:
        """Run until terminal. step_fn() returns the current phase; if it is
        COMPLETE/TERMINAL or the PR is closed, the watcher stops cleanly."""
        if not self.acquire():
            return False
        interval = interval_override or self.interval
        try:
            while True:
                time.sleep(interval)
                if self._terminal():
                    break
                phase = step_fn()
                ws = self._load() or WatcherState(
                    task_id=self.task_id, repo=self.repo, pr=self.pr,
                    pid=os.getpid(), started_at="", last_phase="", last_review="")
                ws.last_phase = phase
                ws.terminated = phase in ("COMPLETE", "TERMINAL")
                self._save(ws)
                self._loopx_refresh(phase, ws.last_review)
                if ws.terminated:
                    print(f"WATCHER_EXIT: {phase}")
                    break
        finally:
            self.release()
        return True
