import unittest
import os
import sys
import json
import tempfile
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from control_watcher import ControlWatcher, WatcherRuntimeState
import control_watcher as cw


class TestControlWatcher(unittest.TestCase):

    def _watcher(self, td, task_id="AGE-T", repo="o/r", pr="7", head="abc"):
        return ControlWatcher(
            task_id=task_id, repo=repo, pr=pr, head=head,
            deliverable_path="docs/plans/X.md",
            deliverable_url="https://github.com/o/r/blob/main/docs/plans/X.md",
            state_dir=td, interval=600,
        )

    def test_snapshot_change_detection(self):
        self.assertTrue(cw.ControlWatcher._changed(
            {"state": "OPEN", "head": "abc"}, {"state": "OPEN", "head": "def"}))
        self.assertTrue(cw.ControlWatcher._changed(
            {"state": "OPEN"}, {"state": "MERGED"}))
        self.assertFalse(cw.ControlWatcher._changed(
            {"state": "OPEN", "head": "abc"}, {"state": "OPEN", "head": "abc"}))
        self.assertFalse(cw.ControlWatcher._changed(None, None))

    def test_single_instance_pid_guard(self):
        with tempfile.TemporaryDirectory() as td:
            w = self._watcher(td)
            self.assertTrue(w.acquire())
            # A second watcher sees the same alive pid -> refuse.
            w2 = self._watcher(td)
            self.assertFalse(w2.acquire())
            w.release()
            # After release, a new watcher can acquire.
            w3 = self._watcher(td)
            self.assertTrue(w3.acquire())
            w3.release()

    def test_runtime_state_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            w = self._watcher(td)
            w.acquire()
            self.assertTrue(os.path.exists(w.state_path))
            with open(w.state_path) as f:
                d = json.load(f)
            self.assertEqual(d["task_id"], "AGE-T")
            self.assertEqual(d["pr"], "7")
            w.release()

    def test_routing_high_stays_waiting(self):
        w = self._watcher("/tmp")
        w.runtime = WatcherRuntimeState(
            task_id="AGE-T", repo="o/r", pr="7", head="abc", pid=1,
            started_at="x", last_github=None, last_linear=None,
            last_route="WAITING_PO_AUTH", last_notify_at=None)
        with mock.patch.object(w, "_should_notify", return_value=False), \
             mock.patch.object(w, "_notify") as mock_notify:
            result = w._handle_change({
                "github": {"state": "OPEN", "head": "abc"},
                "linear": None,
            })
        self.assertEqual(result, "WAITING_PO_AUTH")
        mock_notify.assert_not_called()

    def test_routing_high_notifies_on_change(self):
        w = self._watcher("/tmp")
        w.runtime = WatcherRuntimeState(
            task_id="AGE-T", repo="o/r", pr="7", head="abc", pid=1,
            started_at="x", last_github={"state": "OPEN", "head": "abc"},
            last_linear=None, last_route="WAITING_PO_AUTH", last_notify_at=None)
        with mock.patch.object(w, "_should_notify", return_value=True), \
             mock.patch.object(w, "_notify") as mock_notify:
            result = w._handle_change({
                "github": {"state": "OPEN", "head": "def"},
                "linear": None,
            })
        self.assertEqual(result, "WAITING_PO_AUTH")
        mock_notify.assert_called_once()

    def test_should_notify_compares_prev_snapshot(self):
        # Notify only when the current PR state differs from the PREVIOUS
        # snapshot (not from the just-updated one).
        w = self._watcher("/tmp")
        prev = {"state": "OPEN", "head": "abc", "updated_at": "t1"}
        with mock.patch.object(cw.github_poller, "read_pr_state",
                               return_value={"state": "OPEN", "head": "abc",
                                             "updated_at": "t2"}):
            self.assertTrue(w._should_notify(prev))  # updated_at changed
        with mock.patch.object(cw.github_poller, "read_pr_state",
                               return_value={"state": "OPEN", "head": "abc",
                                             "updated_at": "t1"}):
            self.assertFalse(w._should_notify(prev))  # identical

    def test_terminal_when_merged(self):
        w = self._watcher("/tmp")
        w.runtime = WatcherRuntimeState(
            task_id="AGE-T", repo="o/r", pr="7", head="abc", pid=1,
            started_at="x", last_github={"state": "MERGED"},
            last_linear=None, last_route="WAITING_PO_AUTH", last_notify_at=None)
        self.assertTrue(w._is_terminal())

    def test_terminal_when_linear_done(self):
        w = self._watcher("/tmp")
        w.runtime = WatcherRuntimeState(
            task_id="AGE-T", repo="o/r", pr="7", head="abc", pid=1,
            started_at="x", last_github={"state": "OPEN"},
            last_linear={"state_name": "Done", "state_type": "completed"},
            last_route="WAITING_PO_AUTH", last_notify_at=None)
        self.assertTrue(w._is_terminal())


class TestLinearAdapter(unittest.TestCase):
    def test_unavailable_when_no_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(cw.linear_adapter.linear_available())
            self.assertIsNone(cw.linear_adapter.read_linear_issue("AGE-T"))

    def test_read_linear_real_or_none(self):
        # If token present, read is attempted; on network failure returns None
        # (fail-open, never fabricates). We only assert no exception.
        with mock.patch.dict(os.environ, {"LINEAR_ACCESS_TOKEN": "lin_test"}):
            out = cw.linear_adapter.read_linear_issue("AGE-T")
            self.assertTrue(out is None or isinstance(out, dict))


if __name__ == "__main__":
    unittest.main()
