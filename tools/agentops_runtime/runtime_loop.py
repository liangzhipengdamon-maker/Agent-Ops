#!/usr/bin/env python3
"""AGE-30 AUTO/MANUAL runtime loop (Builder + Controller/Watcher).

Implements CURRENT_RUNTIME_RULES.md:

  AUTO: keep the loop running through in-scope steps until acceptance
        criteria are satisfied. No phase-by-phase PO prompting.
  MANUAL: run the same loop until the task-named checkpoint, then enter
        WAITING_PO_AUTH. Builder may exit; Controller/Watcher stays alive.

  CHANGES_REQUESTED / NOT_PASS -> Builder fixes -> new code HEAD -> review
  PASS -> continue in scope or finish.

Delivery is fail-closed. The Controller terminates only on accepted
completion, closure, or cancellation. No risk classifier participates.
"""

import dataclasses
import json
import os
import subprocess
import time
from typing import Optional

from . import linear_adapter
from .review_intake import read_github_pr, read_pr_head
from .delivery import (
    build_completion_report, NeutralRelayNotifier, GptWebContextReadback,
)


@dataclasses.dataclass
class LoopState:
    task_id: str
    repo: str
    pr: str
    head: str
    mode: str
    phase: str          # INTAKE | IMPLEMENT | REVIEW | FIX | PASSED | COMPLETE | TERMINAL
    review_decision: str
    last_updated: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LoopState":
        return cls(**d)


class RuntimeLoop:
    def __init__(self, task_id: str, repo: str, pr: str, state_dir: str,
                 notifier: Optional[NeutralRelayNotifier] = None,
                 readback: Optional[GptWebContextReadback] = None):
        self.task_id = task_id
        self.repo = repo
        self.pr = str(pr)
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self.state_path = os.path.join(state_dir, f"loop_{task_id}.json")
        self.notifier = notifier or NeutralRelayNotifier()
        self.readback = readback or GptWebContextReadback()

    # -- state persistence -------------------------------------------------
    def load_state(self) -> Optional[LoopState]:
        if not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path) as f:
                return LoopState.from_dict(json.load(f))
        except Exception:
            return None

    def save_state(self, st: LoopState):
        with open(self.state_path, "w") as f:
            json.dump(st.to_dict(), f, indent=2, ensure_ascii=False)

    # -- delivery (fail closed) -------------------------------------------
    def deliver(self, st: LoopState, sections: dict) -> dict:
        head = read_pr_head(self.repo, int(self.pr)) or st.head
        report = build_completion_report(self.repo, self.pr, head, sections)
        out_dir = os.path.join(self.state_dir, "relay")
        d = self.notifier.send(report, out_dir)
        rb = self.readback.verify(report)
        confirmed = d.ack_captured or rb.readback_confirmed
        result = {
            "correlation_id": report.correlation_id,
            "delivered": confirmed,
            "status": "DELIVERED" if confirmed else "DELIVERY_FAILED",
            "readback_confirmed": rb.readback_confirmed,
        }
        return result

    # -- GitHub helpers ---------------------------------------------------
    def _push_code(self, branch: str, commit_msg: str, files: list,
                   cwd: str) -> bool:
        """Commit + push real code changes; returns True if pushed a new HEAD."""
        try:
            subprocess.run(["git", "add", *files], check=True, cwd=cwd)
            subprocess.run(["git", "commit", "-m", commit_msg],
                           check=True, cwd=cwd)
            subprocess.run(["git", "push", "origin", branch], check=True, cwd=cwd)
            return True
        except subprocess.CalledProcessError:
            return False

    # -- Builder remediation handoff (P0-1) ---------------------------------
    def emit_builder_wake(self, st: LoopState, findings: list):
        """Write an actionable Builder wake so NOT_PASS/CHANGES_REQUESTED
        findings auto-return to the Builder, which fixes -> new code HEAD ->
        re-review. This is the real Builder handoff; no PO copy/paste."""
        wake = {
            "type": "BUILDER_WAKE",
            "task_id": self.task_id,
            "repo": self.repo,
            "pr": self.pr,
            "head": st.head,
            "review_decision": st.review_decision,
            "phase": st.phase,
            "findings": findings,
            "action": "apply_fix_and_push_new_head",
            "emitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        wake_path = os.path.join(self.state_dir, f"wake_{self.task_id}.json")
        with open(wake_path, "w") as f:
            json.dump(wake, f, indent=2, ensure_ascii=False)
        return wake_path

    def list_builder_wakes(self) -> list:
        import glob
        wakes = []
        for p in sorted(glob.glob(os.path.join(self.state_dir, "wake_*.json"))):
            try:
                with open(p) as f:
                    wakes.append(json.load(f))
            except Exception:
                continue
        return wakes

    # -- main loop (single wake) -----------------------------------------
    def step(self, mode: str, checkpoint: Optional[str],
             acceptance_ok: bool) -> LoopState:
        """One wake of the loop. Returns the updated state.

        This is the production observable behavior: it reads the real
        GitHub review for the current HEAD and decides the next action.
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        head = read_pr_head(self.repo, int(self.pr)) or ""
        st = self.load_state() or LoopState(
            task_id=self.task_id, repo=self.repo, pr=self.pr, head=head,
            mode=mode, phase="INTAKE", review_decision="", last_updated=now)

        # Terminal conditions: PR closed/merged or task closed.
        gh = _pr_state(self.repo, int(self.pr))
        if gh is None:
            # P0-6: unreadable remote state is NOT terminal. It is a
            # retryable/BLOCKED condition, never accepted closure.
            st.phase = "BLOCKED"
            st.review_decision = "UNREADABLE_REMOTE"
            st.last_updated = now
            self.save_state(st)
            return st
        if gh.get("state") in ("MERGED", "CLOSED"):
            st.phase = "TERMINAL"
            st.last_updated = now
            self.save_state(st)
            return st

        # In AUTO: if acceptance criteria satisfied and review passed, done.
        review = read_github_pr(self.repo, int(self.pr), head or st.head)
        st.head = head or st.head
        st.review_decision = review.decision

        if review.decision == "PASS":
            if acceptance_ok:
                st.phase = "COMPLETE"
            else:
                st.phase = "PASSED"
        elif review.decision in ("CHANGES_REQUESTED", "NOT_PASS"):
            st.phase = "FIX"
            # P0-1: emit the Builder wake so the findings auto-return to the
            # Builder (fix -> new code HEAD -> re-review). No PO copy/paste.
            self.emit_builder_wake(st, review.findings)
        else:
            st.phase = "REVIEW" if st.phase != "FIX" else "FIX"

        # MANUAL: pause only when the named checkpoint is actually reached.
        # For a code task the named checkpoint is the current-HEAD review
        # PASS (the PO decision point named by the task). Only a review
        # bound to the CURRENT head qualifies; stale/older reviews do not.
        if mode == "MANUAL" and checkpoint and review.decision == "PASS":
            st.phase = "WAITING_PO_AUTH"

        st.last_updated = now
        self.save_state(st)
        return st

    def run_auto(self, acceptance_ok: bool, branch: str, cwd: str) -> LoopState:
        """AUTO: keep looping through in-scope steps until acceptance
        satisfied. This implementation performs one bounded step per call
        (one-action-per-wake); the Controller/Watcher calls it repeatedly."""
        st = self.step("AUTO", None, acceptance_ok)
        # If a fix is needed and we have a worktree, the Builder (external)
        # performs the code fix; the loop reflects the new HEAD on the next
        # step. Here we only drive the state machine + delivery.
        self.deliver(st, {"Task": st.task_id,
                          "Phase": st.phase,
                          "Review": st.review_decision,
                          "PR": self.pr,
                          "HEAD": st.head})
        return st


def _pr_state(repo: str, pr: int) -> Optional[dict]:
    import subprocess, json
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json", "state"],
            capture_output=True, text=True, check=True, timeout=30)
        return json.loads(res.stdout)
    except Exception:
        return None
