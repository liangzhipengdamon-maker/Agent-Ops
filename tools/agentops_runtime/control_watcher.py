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


def _waiting_text(route: str) -> str:
    """Route-aware waiting description. A non-PASS review is NEVER reported
    as 'awaiting PO merge authorization'."""
    if route == "WAITING_PO_AUTH":
        return "WAITING_PO_AUTH: review PASS on high risk; awaiting PO decision (merge/deploy)."
    if route == "FOLLOW_UP_REQUIRED":
        return "FOLLOW_UP_REQUIRED: review asked for changes; Builder fixing, then re-review."
    if route == "WAIT_REVIEW":
        return "WAIT_REVIEW: awaiting reviewer opinion (not yet PASS)."
    if route == "GPT_DECISION_REQUIRED":
        return "GPT_DECISION_REQUIRED: awaiting GPT Web decision on medium risk."
    if route == "AUTO_CONTINUE":
        return "AUTO_CONTINUE: low risk, resuming execution."
    if route == "DELIVERY_FAILED":
        return "DELIVERY_FAILED: PO notification not confirmed; not in WAITING_PO_AUTH."
    return f"awaiting next step ({route or 'unknown'})"


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
    last_risk: Optional[str] = "HIGH"

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
    def _dynamic_risk(self, gh: dict, lin: dict, review_decision: str) -> str:
        """Re-evaluate risk from the CHANGED evidence (not the launch risk).

        Fail closed: default to HIGH unless there is positive evidence of a
        lower-risk continuation.

        Positive downgrade signals (AGE-29 aligned, conservative):
        - LINEAR completed / Done + PR open but not high-risk -> LOW (resume).
        - Linear moved to a normal startable state + review CHANGES_REQUESTED
          -> MEDIUM (follow-up needs GPT decision).
        - Otherwise -> HIGH (unchanged, stays WAITING_PO_AUTH).
        """
        lin_state = (lin or {}).get("state_name") or ""
        lin_type = (lin or {}).get("state_type") or ""
        gh_state = (gh or {}).get("state") or ""

        if gh_state == "MERGED":
            # terminal handled elsewhere; treat as not-a-continuation
            return "HIGH"
        if lin_type == "completed" or lin_state == "Done":
            # Linear task completed and PR still open: a LOW-risk continuation
            # (e.g. update deliverable, finalize docs). Resume.
            if review_decision in ("PASS", "CHANGES_REQUESTED"):
                return "LOW"
            return "LOW"
        if review_decision == "CHANGES_REQUESTED":
            # Follow-up work on the reviewed change: GPT decision required.
            return "MEDIUM"
        if review_decision == "PASS":
            # Reviewed PASS but task not Done: still wait for PO on any
            # high-risk action; conservative HIGH.
            return "HIGH"
        return "HIGH"

    def _handle_change(self, snap: dict):
        gh = snap.get("github") or {}
        lin = snap.get("linear") or {}

        # Re-read the authoritative review decision.
        review = read_github_pr(self.repo, int(self.pr), gh.get("head") or self.head)
        review_decision = review.decision if review else "INCOMPLETE"

        # DYNAMIC risk from the changed evidence (not hardcoded HIGH).
        risk = self._dynamic_risk(gh, lin, review_decision)
        outcome = route_decision(risk, review_decision)

        route = outcome.route
        prev_gh = self.runtime.last_github
        prev_lin = self.runtime.last_linear
        self.runtime.last_github = gh
        self.runtime.last_linear = lin
        self.runtime.last_route = route
        self.runtime.last_risk = risk
        self._write_runtime()

        if route == "AUTO_CONTINUE":
            print(f"WATCHER_ROUTE: AUTO_CONTINUE (task {self.task_id}, risk={risk})")
            self._emit_builder_wake("resume", route, review_decision)
            self._notify("resume", route)
            return "AUTO_CONTINUE"

        if route == "GPT_DECISION_REQUIRED":
            print(f"WATCHER_ROUTE: GPT_DECISION_REQUIRED (task {self.task_id}, "
                  f"risk={risk})")
            self._emit_builder_wake("gpt_decision_follow_up", route, review_decision)
            self._notify("gpt_decision", route)
            return "GPT_DECISION_REQUIRED"

        if route == "FOLLOW_UP_REQUIRED":
            # Review said CHANGES_REQUESTED (even on HIGH): the Builder must
            # fix, then the task re-enters the review loop. NOT awaiting merge.
            print(f"WATCHER_ROUTE: FOLLOW_UP_REQUIRED (task {self.task_id}, "
                  f"risk={risk}, review={review_decision})")
            self._emit_builder_wake("review_follow_up", route, review_decision)
            self._notify("review_follow_up", route)
            return "FOLLOW_UP_REQUIRED"

        if route == "WAIT_REVIEW":
            # Review opinion is not yet PASS (COMMENTED/BLOCKED/INCOMPLETE):
            # await the reviewer opinion, then the Builder acts.
            print(f"WATCHER_ROUTE: WAIT_REVIEW (task {self.task_id}, "
                  f"risk={risk}, review={review_decision})")
            self._emit_builder_wake("await_review_opinion", route, review_decision)
            self._notify("await_review_opinion", route)
            return "WAIT_REVIEW"

        if route == "WAITING_PO_AUTH":
            # HIGH: stay; notify GPT/PO only when new info actually changed
            # relative to the PREVIOUS snapshot (avoid per-tick spam).
            print(f"WATCHER_ROUTE: WAITING_PO_AUTH (task {self.task_id}, "
                  f"risk={risk}, review={review_decision})")
            if self._should_notify(prev_gh):
                # Emit the Builder wake FIRST (before the blocking notify) so
                # the Builder can act immediately: any detected change on a
                # HIGH task means the Builder must read GitHub and fix.
                self._emit_builder_wake(
                    "high_state_change", route, review_decision)
                self._notify("high_state_change", route)
            return "WAITING_PO_AUTH"

        print(f"WATCHER_ROUTE: {route} (task {self.task_id}, "
              f"risk={risk}, review={review_decision})")
        return route

    def _should_notify(self, prev_gh: Optional[dict]) -> bool:
        # Notify only when meaningful GitHub state changed relative to the
        # PREVIOUS snapshot. None-vs-None is not a change.
        cur = github_poller.read_pr_state(self.repo, self.pr)
        return self._changed(prev_gh, cur)

    def _emit_builder_wake(self, reason: str, route: str, review_decision: str):
        """Write an actionable BUILDER_WAKE event for the Builder to consume.

        This is the mechanism that drives the Builder to FIX the review
        findings: the watcher does not fix code itself; it emits a wake
        event (repo/pr/head/review/route/action) that the Builder consumes
        on its next wake, executes the follow-up, commits, pushes, and the
        watcher then re-evaluates the new HEAD.
        """
        os.makedirs(self.state_dir, exist_ok=True)
        wake = {
            "type": "BUILDER_WAKE",
            "task_id": self.task_id,
            "repo": self.repo,
            "pr": self.pr,
            "head": github_poller.read_pr_head(self.repo, self.pr) or self.head,
            "review_decision": review_decision,
            "route": route,
            "reason": reason,
            "action": "execute_follow_up",
            "emitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        wake_path = os.path.join(self.state_dir, f"wake_{self.task_id}.json")
        with open(wake_path, "w") as f:
            json.dump(wake, f, indent=2, ensure_ascii=False)
        print(f"WATCHER_BUILDER_WAKE: {wake_path}")

    def _notify(self, reason: str, route: str = ""):
        if not self.deliverable_path:
            return
        # Bind the notify to the CURRENT live PR HEAD, not the launch-time
        # head: the PR may have advanced while the task sat at
        # WAITING_PO_AUTH. This keeps the Completion Report exact.
        live_head = github_poller.read_pr_head(self.repo, self.pr) or self.head
        # Waiting text is route-aware, not hardcoded. A non-PASS review must
        # NOT be reported as "awaiting PO merge authorization".
        waiting_text = _waiting_text(route or reason)
        sections = {
            "Task": f"{self.task_id}",
            "Status": f"Control Watcher detected a change and routed: {reason}",
            "Fixed behavior": "Watcher keeps running after Builder exits; "
                              "WAITING_PO_AUTH is a start condition, not termination.",
            "Implementation": "tools/agentops_runtime/control_watcher.py",
            "Live validation evidence": "GitHub + Linear polled; change detected; "
                                        "existing Review/Risk/Transition path invoked.",
            "PR/branch/HEAD": f"pr {self.pr} / {self.repo} / {live_head}",
            "Deliverable": f"{self.deliverable_path}",
            "Deliverable URL": self.deliverable_url,
            "Boundaries": "No merge, no deploy, no PO bypass.",
            "Waiting": waiting_text,
        }
        report = build_completion_report(
            task_id=self.task_id, repo=self.repo, pr=self.pr, head=live_head,
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
