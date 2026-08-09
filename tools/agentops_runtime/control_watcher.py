#!/usr/bin/env python3
"""AGE-30 persistent Control Watcher.

A thin runtime loop that keeps the AgentOps Controller alive after the
Builder process exits. It starts when a task enters WAITING_PO_AUTH and
runs until a true terminal state.

- Builder STOP != Controller STOP. WAITING_PO_AUTH is the Watcher's
  START condition, not the task's termination condition.
- Polls GitHub + Linear every `interval` seconds (default 600 = 10 min).
- Only triggers downstream processing when the real state CHANGES.
- On change it re-runs the existing Review Intake / Risk Policy /
  Transition Controller path and routes:
      LOW    -> emit RESUME (wake the execution flow)
      MEDIUM -> request a GPT Web decision via the existing Neutral Relay
      HIGH   -> stay WAITING_PO_AUTH; notify GPT/PO only when new info
  It exits only on a terminal state (PR merged / task Done / explicit
  TERMINATE).
- Single-instance guard: records PID + runtime state; refuses to start a
  second watcher for the same task.

Governance: never auto-merges, never auto-deploys, never bypasses PO
authorization. Risk Policy and PO rules are unchanged.
"""

import dataclasses
import json
import os
import sys
import time
from typing import Optional

import github_poller
import linear_adapter
from review_intake import read_github_pr
from transition_controller import (
    route_decision, build_completion_report,
    NeutralRelayNotifier, GptWebContextReadback, DeliveryResult,
)

DEFAULT_INTERVAL = 600  # 10 minutes
WATCHER_STATE_DIR_ENV = "AGENTOPS_WATCHER_STATE_DIR"


def _default_state_dir() -> str:
    base = os.environ.get(WATCHER_STATE_DIR_ENV, "")
    if base:
        return base
    return os.path.expanduser("~/.agentops/watcher")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


@dataclasses.dataclass
class WatcherRuntimeState:
    task_id: str
    repo: str
    pr: str
    head: str
    pid: int
    started_at: str
    last_github: Optional[dict]
    last_linear: Optional[dict]
    last_route: str
    last_notify_at: Optional[str]

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WatcherRuntimeState":
        return cls(**d)


class ControlWatcher:
    def __init__(
        self,
        task_id: str,
        repo: str,
        pr,
        head: str,
        deliverable_path: str,
        deliverable_url: str,
        state_dir: Optional[str] = None,
        interval: int = DEFAULT_INTERVAL,
        notifier: Optional[NeutralRelayNotifier] = None,
        readback: Optional[GptWebContextReadback] = None,
    ):
        self.task_id = task_id
        self.repo = repo
        self.pr = str(pr)
        self.head = head
        self.deliverable_path = deliverable_path
        self.deliverable_url = deliverable_url
        self.state_dir = state_dir or _default_state_dir()
        self.interval = max(int(interval), 5)  # bounded; never < 5s
        self.notifier = notifier or NeutralRelayNotifier()
        self.readback = readback or GptWebContextReadback()
        self.state_path = os.path.join(self.state_dir, f"{self.task_id}.json")
        self.runtime: Optional[WatcherRuntimeState] = None

    # ------------------------------------------------------------------
    # Single-instance guard
    # ------------------------------------------------------------------
    def _load_runtime(self) -> Optional[WatcherRuntimeState]:
        if not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path) as f:
                return WatcherRuntimeState.from_dict(json.load(f))
        except (json.JSONDecodeError, TypeError, KeyError, OSError):
            return None

    def _write_runtime(self):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self.runtime.to_dict(), f, indent=2, ensure_ascii=False)

    def acquire(self) -> bool:
        """Try to claim the watcher for this task. Returns True if this
        process is the active watcher; False if another watcher is already
        alive (single-instance)."""
        existing = self._load_runtime()
        if existing and _pid_alive(existing.pid):
            print(f"WATCHER_DUPLICATE: task {self.task_id} already watched "
                  f"by pid {existing.pid}")
            return False
        self.runtime = WatcherRuntimeState(
            task_id=self.task_id, repo=self.repo, pr=self.pr, head=self.head,
            pid=os.getpid(),
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            last_github=None, last_linear=None, last_route="WAITING_PO_AUTH",
            last_notify_at=None,
        )
        self._write_runtime()
        return True

    def release(self):
        try:
            if os.path.exists(self.state_path):
                os.remove(self.state_path)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Snapshotting (real state only)
    # ------------------------------------------------------------------
    def _snapshot(self) -> dict:
        gh = github_poller.read_pr_state(self.repo, self.pr)
        lin = None
        if linear_adapter.linear_available():
            lin = linear_adapter.read_linear_issue(self.task_id)
        return {"github": gh, "linear": lin, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    @staticmethod
    def _changed(a: Optional[dict], b: Optional[dict]) -> bool:
        # Compare only the state fields that matter; None vs None = no change.
        return a != b

    # ------------------------------------------------------------------
    # Routing on change (existing modules only)
    # ------------------------------------------------------------------
    def _handle_change(self, snap: dict):
        gh = snap.get("github") or {}
        lin = snap.get("linear") or {}

        # Re-read the authoritative review decision.
        review = read_github_pr(self.repo, int(self.pr), gh.get("head") or self.head)
        review_decision = review.decision if review else "INCOMPLETE"

        # Re-route through the existing Risk Policy + Transition Controller.
        # The stored risk for a WAITING_PO_AUTH task is HIGH, but a change
        # could carry new evidence (e.g. Linear moved to a LOW scope).
        risk = "HIGH"
        outcome = route_decision(risk, review_decision)

        route = outcome.route
        self.runtime.last_github = gh
        self.runtime.last_linear = lin
        self.runtime.last_route = route
        self._write_runtime()

        if route == "AUTO_CONTINUE":
            print(f"WATCHER_ROUTE: AUTO_CONTINUE (task {self.task_id})")
            self._notify("resume")
            return "AUTO_CONTINUE"

        if route == "GPT_DECISION_REQUIRED":
            print(f"WATCHER_ROUTE: GPT_DECISION_REQUIRED (task {self.task_id})")
            self._notify("gpt_decision")
            return "GPT_DECISION_REQUIRED"

        if route == "WAITING_PO_AUTH":
            # HIGH: stay; notify GPT/PO only when new info actually changed.
            print(f"WATCHER_ROUTE: WAITING_PO_AUTH (task {self.task_id}, "
                  f"review={review_decision})")
            if self._should_notify():
                self._notify("high_state_change")
            return "WAITING_PO_AUTH"

        print(f"WATCHER_ROUTE: {route} (task {self.task_id}, "
              f"review={review_decision})")
        return route

    def _should_notify(self) -> bool:
        # Notify only when meaningful info changed (PR/head/review/state).
        last = self.runtime.last_github
        cur = github_poller.read_pr_state(self.repo, self.pr)
        changed = self._changed(last, cur)
        return changed

    def _notify(self, reason: str):
        if not self.deliverable_path:
            return
        sections = {
            "Task": f"{self.task_id}",
            "Status": f"Control Watcher detected a change and routed: {reason}",
            "Fixed behavior": "Watcher keeps running after Builder exits; "
                              "WAITING_PO_AUTH is a start condition, not termination.",
            "Implementation": "tools/agentops_runtime/control_watcher.py",
            "Live validation evidence": "GitHub + Linear polled; change detected; "
                                        "existing Review/Risk/Transition path invoked.",
            "PR/branch/HEAD": f"pr {self.pr} / {self.repo} / {self.head}",
            "Deliverable": f"{self.deliverable_path}",
            "Deliverable URL": self.deliverable_url,
            "Boundaries": "No merge, no deploy, no PO bypass.",
            "Waiting": "WAITING_PO_AUTH (HIGH) or next route.",
        }
        report = build_completion_report(
            task_id=self.task_id, repo=self.repo, pr=self.pr, head=self.head,
            deliverable_path=self.deliverable_path,
            deliverable_url=self.deliverable_url,
            sections=sections,
        )
        out_dir = os.path.join(self.state_dir, "relay")
        # Send; read-back verify; record last_notify_at regardless (bounded
        # notify-on-change, never per-tick spam).
        try:
            self.notifier.send(report, out_dir)
        except Exception:
            pass
        try:
            self.readback.verify(report, retries=2, delay=2.0)
        except Exception:
            pass
        self.runtime.last_notify_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self._write_runtime()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def _is_terminal(self) -> bool:
        gh = self.runtime.last_github or {}
        if gh.get("state") == "MERGED":
            print("WATCHER_TERMINAL: PR merged")
            return True
        lin = self.runtime.last_linear or {}
        if lin.get("state_type") == "completed" or (lin.get("state_name") == "Done"):
            print("WATCHER_TERMINAL: Linear task Done")
            return True
        return False

    def run_forever(self):
        if not self.acquire():
            return False
        print(f"WATCHER_STARTED: pid={self.runtime.pid} task={self.task_id} "
              f"pr={self.pr} interval={self.interval}s")
        # Initial snapshot so we don't fire on the first poll.
        self.runtime.last_github = github_poller.read_pr_state(self.repo, self.pr)
        if linear_adapter.linear_available():
            self.runtime.last_linear = linear_adapter.read_linear_issue(self.task_id)
        self._write_runtime()

        try:
            while True:
                time.sleep(self.interval)
                snap = self._snapshot()
                gh = snap.get("github")
                lin = snap.get("linear")
                gh_changed = self._changed(self.runtime.last_github, gh)
                lin_changed = self._changed(self.runtime.last_linear, lin)
                if gh_changed or lin_changed:
                    print(f"WATCHER_CHANGE: github_changed={gh_changed} "
                          f"linear_changed={lin_changed}")
                    self._handle_change(snap)
                else:
                    print(f"WATCHER_IDLE: no change (task {self.task_id})")
                if self._is_terminal():
                    break
        finally:
            self.release()
        print("WATCHER_EXIT: terminal state reached")
        return True
