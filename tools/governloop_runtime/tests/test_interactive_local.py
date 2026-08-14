"""Tests for the interactive_local positive authority fallback.

These cover the mode-aware verify chain (verify_task_scope /
apply_verified_authority), the fence-layer mode plumbing
(builder_handoff / _verified_scope_policy), and the one-time YES-from-stdin
confirmation path used by ``governloop setup-task-scope``. Nothing here
creates a same-uid writable record outside the test's tempfile sandbox —
``operator_channel.os_account_home`` is patched to a tmpdir for every test.
"""

from __future__ import annotations

import argparse
import inspect
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock


BASE = "0123456789abcdef0123456789abcdef01234567"
HEAD_PIN = "fedcba9876543210fedcba9876543210fedcba98"
ALT_BRANCH = "feat/x"
ALT_REPO = "owner/repo"


def _task_scope_payload(**overrides):
    payload = {
        "schema": "governloop-task-scope-v1",
        "authority_id": "interactive-local-AGE-IL",
        "task_id": "AGE-IL",
        "repository": ALT_REPO,
        "branch": ALT_BRANCH,
        "baseline_sha": BASE,
        "head_sha": HEAD_PIN,
        "allowed_paths": ["tools/"],
        "allowed_operations": ["fix", "continue", "complete"],
        "trusted_reviewers": ["trusted-reviewer"],
        "bound_at": "2026-08-14T00:00:00Z",
        "confirmation_method": "interactive_local_tty_yes",
    }
    payload.update(overrides)
    payload["integrity_sha256"] = _integrity_of(payload)
    return payload


def _integrity_of(payload: dict) -> str:
    import hashlib
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in payload.items() if k != "integrity_sha256"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _signed_authority_payload():
    return {
        "schema": "governloop-authority-v2",
        "authority_id": "external-test-authority",
        "task_id": "AGE-IL",
        "repository": ALT_REPO,
        "branch": ALT_BRANCH,
        "baseline_sha": BASE,
        "allowed_paths": ["tools/"],
        "allowed_operations": ["fix", "continue", "complete"],
        "trusted_reviewers": ["trusted-reviewer"],
    }


def _git_run_factory(observed_branch: str, porcelain: str = ""):
    """Return a subprocess.run side_effect that simulates git rev-parse/status
    in the sandbox. Anything else falls through to a real subprocess."""
    def side_effect(args, **kwargs):
        if isinstance(args, list) and len(args) >= 2 and args[0] == "git":
            m = mock.MagicMock()
            if args[1] == "rev-parse" and "--abbrev-ref" in args:
                m.returncode = 0
                m.stdout = observed_branch
                m.stderr = ""
                return m
            if args[1] == "status":
                m.returncode = 0
                m.stdout = porcelain
                m.stderr = ""
                return m
            if args[1] == "remote":
                m.returncode = 0
                m.stdout = f"https://github.com/{ALT_REPO}.git"
                m.stderr = ""
                return m
        return mock.DEFAULT
    return side_effect


class _TaskScopeHome(unittest.TestCase):
    """Sandbox the OS-account-home resolution into a tmpdir for every test."""

    def setUp(self):
        self._tmp_home = tempfile.mkdtemp(prefix="gl-il-home-")
        from pathlib import Path
        self._patch_home = mock.patch(
            "governloop_runtime.operator_channel.os_account_home",
            return_value=Path(self._tmp_home))
        self._patch_home.start()

    def tearDown(self):
        self._patch_home.stop()
        import shutil
        shutil.rmtree(self._tmp_home, ignore_errors=True)

    def _record_path(self, task_id: str) -> str:
        return os.path.join(
            self._tmp_home, ".governloop", "task_scope", f"{task_id}.json")

    def _write(self, task_id: str, payload: dict):
        target = self._record_path(task_id)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return target


# ---------------------------------------------------------------------------- #
# A. verify_task_scope  +  integrity_sha256 / confirmation_method provenance #
# ---------------------------------------------------------------------------- #


class VerifyTaskScopeTests(_TaskScopeHome):
    def test_accepts_complete_record(self):
        from governloop_runtime import authority
        self._write("AGE-IL", _task_scope_payload())
        out = authority.verify_task_scope("AGE-IL", expected_repo=ALT_REPO)
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("status"), "INTERACTIVE_LOCAL")
        self.assertEqual(out.get("head_sha"), HEAD_PIN)
        self.assertEqual(out["payload"]["baseline_sha"], BASE)

    def test_rejects_wrong_task_id(self):
        from governloop_runtime import authority
        self._write("AGE-IL", _task_scope_payload(task_id="OTHER"))
        out = authority.verify_task_scope("AGE-IL", expected_repo=ALT_REPO)
        self.assertFalse(out.get("ok"))
        self.assertIn("task_id binding", out.get("detail", ""))

    def test_rejects_wrong_repo(self):
        from governloop_runtime import authority
        self._write("AGE-IL", _task_scope_payload(repository="attacker/repo"))
        out = authority.verify_task_scope("AGE-IL", expected_repo=ALT_REPO)
        self.assertFalse(out.get("ok"))
        self.assertIn("repository", out.get("detail", ""))

    def test_rejects_invalid_baseline_sha(self):
        from governloop_runtime import authority
        self._write("AGE-IL", _task_scope_payload(baseline_sha="not-a-sha"))
        out = authority.verify_task_scope("AGE-IL", expected_repo=ALT_REPO)
        self.assertFalse(out.get("ok"))
        self.assertIn("baseline_sha", out.get("detail", ""))

    def test_rejects_lifecycle_op_in_allowed_operations(self):
        from governloop_runtime import authority
        self._write("AGE-IL", _task_scope_payload(
            allowed_operations=["fix", "merge"]))
        out = authority.verify_task_scope("AGE-IL", expected_repo=ALT_REPO)
        self.assertFalse(out.get("ok"))
        self.assertIn("lifecycle", out.get("detail", ""))

    def test_rejects_wrong_confirmation_method(self):
        from governloop_runtime import authority
        self._write("AGE-IL", _task_scope_payload(
            confirmation_method="manual_paste"))
        out = authority.verify_task_scope("AGE-IL", expected_repo=ALT_REPO)
        self.assertFalse(out.get("ok"))
        self.assertIn("confirmation_method", out.get("detail", ""))

    def test_rejects_tampered_integrity_sha256(self):
        from governloop_runtime import authority
        payload = _task_scope_payload()
        payload["branch"] = "feat/y"  # mutate after hash → provenance breaks
        self._write("AGE-IL", payload)
        out = authority.verify_task_scope("AGE-IL", expected_repo=ALT_REPO)
        self.assertFalse(out.get("ok"))
        self.assertIn("integrity_sha256", out.get("detail", ""))

    def test_rejects_missing_required_field(self):
        from governloop_runtime import authority
        self._write("AGE-IL", _task_scope_payload(allowed_paths=[]))
        out = authority.verify_task_scope("AGE-IL", expected_repo=ALT_REPO)
        self.assertFalse(out.get("ok"))

    def test_accepts_omitted_head_sha(self):
        from governloop_runtime import authority
        self._write("AGE-IL", _task_scope_payload(head_sha=""))
        out = authority.verify_task_scope("AGE-IL", expected_repo=ALT_REPO)
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("head_sha"), "")


# ---------------------------------------------------------------------------- #
# B. apply_verified_authority : mode 分流 + trusted_reviewers 总是投影        #
# ---------------------------------------------------------------------------- #


class ApplyVerifiedAuthorityModeTests(unittest.TestCase):
    _CLEAR = [
        "AGENTOPS_AUTHORITY_VERIFIED", "AGENTOPS_AUTHORITY_ERROR",
        "AGENTOPS_AUTHORITY_SOURCE",
        "AGENTOPS_SCOPE_REPOSITORY", "AGENTOPS_AUTHORIZED_BRANCH",
        "AGENTOPS_BASELINE_SHA", "AGENTOPS_ALLOWED_PATHS",
        "AGENTOPS_AUTHORIZED_OPERATIONS", "AGENTOPS_TRUSTED_REVIEWERS",
        "GOVERNLOOP_SCOPE_REPOSITORY", "GOVERNLOOP_AUTHORIZED_BRANCH",
        "GOVERNLOOP_BASELINE_SHA", "GOVERNLOOP_ALLOWED_PATHS",
        "GOVERNLOOP_AUTHORIZED_OPERATIONS", "GOVERNLOOP_TRUSTED_REVIEWERS",
    ]

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self._CLEAR}
        for k in self._CLEAR:
            os.environ.pop(k, None)

    def tearDown(self):
        for k in self._CLEAR:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_signed_mode_default_unchanged(self):
        from governloop_runtime import authority
        with mock.patch.object(authority, "verify_authority",
                                return_value={"ok": True,
                                              "payload": _signed_authority_payload(),
                                              "path": "/x",
                                              "authority_id": "external-test-authority",
                                              "missing": [],
                                              "detail": "signed"}):
            out = authority.apply_verified_authority(
                "AGE-IL", expected_repo=ALT_REPO)
        self.assertTrue(out.get("ok"))
        self.assertEqual(os.environ["AGENTOPS_AUTHORITY_VERIFIED"], "1")
        self.assertEqual(os.environ["AGENTOPS_TRUSTED_REVIEWERS"], "trusted-reviewer")
        self.assertEqual(os.environ["GOVERNLOOP_TRUSTED_REVIEWERS"], "trusted-reviewer")

    def test_interactive_local_signed_path_wins_no_task_scope_read(self):
        from governloop_runtime import authority
        with mock.patch.object(authority, "verify_authority",
                                return_value={"ok": True,
                                              "payload": _signed_authority_payload(),
                                              "path": "/x",
                                              "authority_id": "external-test-authority",
                                              "missing": [],
                                              "detail": "signed"}), \
             mock.patch.object(authority, "verify_task_scope") as ts:
            out = authority.apply_verified_authority(
                "AGE-IL", expected_repo=ALT_REPO, mode="interactive_local")
        self.assertTrue(out.get("ok"))
        ts.assert_not_called()
        self.assertEqual(os.environ["AGENTOPS_AUTHORITY_VERIFIED"], "1")
        self.assertEqual(os.environ["AGENTOPS_AUTHORITY_SOURCE"], "signed")

    def test_interactive_local_falls_back_to_task_scope(self):
        from governloop_runtime import authority
        ts_payload = _task_scope_payload()
        signed_failed = {"ok": False, "missing": [], "status": "BLOCKED",
                          "detail": "no signed authority"}
        with mock.patch.object(authority, "verify_authority",
                                return_value=signed_failed), \
             mock.patch.object(authority, "verify_task_scope",
                                return_value={"ok": True,
                                              "status": "INTERACTIVE_LOCAL",
                                              "payload": ts_payload,
                                              "authority_id": ts_payload["authority_id"],
                                              "path": "/x",
                                              "missing": [],
                                              "head_sha": HEAD_PIN,
                                              "detail": "task-scope"}):
            out = authority.apply_verified_authority(
                "AGE-IL", expected_repo=ALT_REPO, mode="interactive_local")
        self.assertTrue(out.get("ok"))
        self.assertEqual(os.environ["AGENTOPS_AUTHORITY_VERIFIED"], "1")
        self.assertEqual(os.environ["AGENTOPS_SCOPE_REPOSITORY"], ALT_REPO)
        self.assertEqual(os.environ["GOVERNLOOP_BASELINE_SHA"], BASE)
        self.assertEqual(os.environ["AGENTOPS_TRUSTED_REVIEWERS"], "trusted-reviewer")
        self.assertEqual(os.environ["AGENTOPS_AUTHORITY_SOURCE"], "interactive_local")

    def test_interactive_local_both_fail_is_blocked(self):
        from governloop_runtime import authority
        with mock.patch.object(authority, "verify_authority",
                                return_value={"ok": False, "missing": ["repository"],
                                              "status": "BLOCKED",
                                              "detail": "signed unavailable"}), \
             mock.patch.object(authority, "verify_task_scope",
                                return_value={"ok": False, "missing": ["repository"],
                                              "status": "BLOCKED",
                                              "detail": "no task-scope"}):
            out = authority.apply_verified_authority(
                "AGE-IL", expected_repo=ALT_REPO, mode="interactive_local")
        self.assertFalse(out.get("ok"))
        self.assertEqual(os.environ["AGENTOPS_AUTHORITY_VERIFIED"], "0")
        self.assertTrue(os.environ["AGENTOPS_AUTHORITY_ERROR"])
        # raw positive fields not projected when nothing resolved:
        self.assertNotIn("AGENTOPS_SCOPE_REPOSITORY", os.environ)
        self.assertNotIn("GOVERNLOOP_BASELINE_SHA", os.environ)


# ----------------------------------------------------------------------- #
# C. builder_handoff / _verified_scope_policy mode 贯通 + head pin 语义   #
# ----------------------------------------------------------------------- #


class FenceModeTests(unittest.TestCase):
    def _policy(self, head_pin=""):
        from agentops_runtime.scope_firewall import ScopePolicy
        return ScopePolicy(
            task_id="AGE-IL", repository=ALT_REPO, branch=ALT_BRANCH,
            base_sha=BASE, head_sha=head_pin,
            allowed_paths=("tools/",),
            allowed_operations=("fix", "continue", "complete"),
            protected_repositories=(
                "liangzhipengdamon-maker/LearnMind-English",
                "liangzhipengdamon-maker/AI-Investment-Lab"),
            allowed_ready_merge_deploy=False,
            binding_ok=True, authoritative_changed_files=(),
            changed_files_unreadable=False,
        )

    def test_resolve_mode_defaults_to_signed(self):
        from agentops_runtime import runtime_loop
        os.environ.pop("AGENTOPS_MODE", None)
        self.assertEqual(runtime_loop._resolve_mode(), "signed")

    def test_resolve_mode_reads_interactive_local(self):
        from agentops_runtime import runtime_loop
        os.environ["AGENTOPS_MODE"] = "interactive_local"
        try:
            self.assertEqual(runtime_loop._resolve_mode(), "interactive_local")
        finally:
            os.environ.pop("AGENTOPS_MODE", None)

    def test_verified_scope_policy_head_pin_comes_only_from_task_scope(self):
        from agentops_runtime import runtime_loop
        from governloop_runtime import authority
        ts_payload = _task_scope_payload()
        signed_failed = {"ok": False, "missing": [], "status": "BLOCKED",
                          "detail": "no signed"}
        with mock.patch.object(authority, "verify_authority",
                                return_value=signed_failed), \
             mock.patch.object(authority, "verify_task_scope",
                                return_value={"ok": True,
                                              "status": "INTERACTIVE_LOCAL",
                                              "payload": ts_payload,
                                              "authority_id": ts_payload["authority_id"],
                                              "path": "/x",
                                              "missing": [],
                                              "head_sha": HEAD_PIN,
                                              "detail": "task-scope"}):
            policy = runtime_loop._verified_scope_policy(
                "AGE-IL", ALT_REPO, "irrelevant-caller-head",
                mode="interactive_local")
        self.assertTrue(policy.binding_ok)
        # head_sha is the task-scope pin, NOT caller head.
        self.assertEqual(policy.head_sha, HEAD_PIN)
        self.assertEqual(policy.base_sha, BASE)

    def test_builder_handoff_writes_status_json_via_task_scope(self):
        from agentops_runtime import runtime_loop
        from governloop_runtime import authority
        ts_payload = _task_scope_payload()
        signed_failed = {"ok": False, "missing": [], "status": "BLOCKED",
                          "detail": "no signed"}
        tmpdir = tempfile.mkdtemp(prefix="gl-il-bridge-")
        try:
            os.environ["AGENT_BRIDGE_DIR"] = tmpdir
            with mock.patch.object(authority, "verify_authority",
                                    return_value=signed_failed), \
                 mock.patch.object(authority, "verify_task_scope",
                                    return_value={"ok": True,
                                                  "status": "INTERACTIVE_LOCAL",
                                                  "payload": ts_payload,
                                                  "authority_id": ts_payload["authority_id"],
                                                  "path": "/x",
                                                  "missing": [],
                                                  "head_sha": HEAD_PIN,
                                                  "detail": "task-scope"}), \
                 mock.patch.object(runtime_loop.subprocess, "run",
                                    side_effect=_git_run_factory(ALT_BRANCH)):
                out = runtime_loop.builder_handoff(
                    "AGE-IL", ALT_REPO, "42", HEAD_PIN, "BUILDER_FIXING", [],
                    policy=self._policy(), observed_branch=ALT_BRANCH,
                    observed_base=BASE, mode="interactive_local")
            self.assertTrue(out.get("ok"), msg=out)
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "status.json")))
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
            os.environ.pop("AGENT_BRIDGE_DIR", None)

    def test_builder_handoff_blocks_when_both_sources_fail(self):
        from agentops_runtime import runtime_loop
        from governloop_runtime import authority
        signed_failed = {"ok": False, "missing": [], "status": "BLOCKED",
                          "detail": "no signed authority"}
        ts_failed = {"ok": False, "missing": [], "status": "BLOCKED",
                       "detail": "no task-scope"}
        # binding_ok will be False before reaching the git/state subtree
        with mock.patch.object(authority, "verify_authority",
                                return_value=signed_failed), \
             mock.patch.object(authority, "verify_task_scope",
                                return_value=ts_failed):
            out = runtime_loop.builder_handoff(
                "AGE-IL", ALT_REPO, "42", HEAD_PIN, "BUILDER_FIXING", [],
                policy=self._policy(), observed_branch=ALT_BRANCH,
                observed_base=BASE, mode="interactive_local")
        self.assertTrue(out.get("blocked"))
        self.assertFalse(out.get("ok"))
        self.assertIn("signed", out.get("reason", ""))

    def test_builder_handoff_head_pin_drift_blocks(self):
        from agentops_runtime import runtime_loop
        from governloop_runtime import authority
        ts_payload = _task_scope_payload()  # pin HEAD_PIN
        signed_failed = {"ok": False, "missing": [], "status": "BLOCKED",
                          "detail": "no signed"}
        tmpdir = tempfile.mkdtemp(prefix="gl-il-bridge-")
        try:
            os.environ["AGENT_BRIDGE_DIR"] = tmpdir
            with mock.patch.object(authority, "verify_authority",
                                    return_value=signed_failed), \
                 mock.patch.object(authority, "verify_task_scope",
                                    return_value={"ok": True,
                                                  "status": "INTERACTIVE_LOCAL",
                                                  "payload": ts_payload,
                                                  "authority_id": ts_payload["authority_id"],
                                                  "path": "/x",
                                                  "missing": [],
                                                  "head_sha": HEAD_PIN,
                                                  "detail": "task-scope"}), \
                 mock.patch.object(runtime_loop.subprocess, "run",
                                    side_effect=_git_run_factory(ALT_BRANCH)):
                drifted = "1" * 40
                out = runtime_loop.builder_handoff(
                    "AGE-IL", ALT_REPO, "42", drifted, "BUILDER_FIXING", [],
                    policy=self._policy(head_pin=HEAD_PIN),
                    observed_branch=ALT_BRANCH, observed_base=BASE,
                    mode="interactive_local")
            self.assertTrue(out.get("blocked"))
            self.assertFalse(out.get("ok"))
            self.assertIn("head_sha", out.get("reason", ""))
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
            os.environ.pop("AGENT_BRIDGE_DIR", None)

    def test_builder_handoff_no_head_pin_means_pr_head_can_drift(self):
        from agentops_runtime import runtime_loop
        from governloop_runtime import authority
        ts_payload = _task_scope_payload(head_sha="")  # no pin
        signed_failed = {"ok": False, "missing": [], "status": "BLOCKED",
                          "detail": "no signed"}
        tmpdir = tempfile.mkdtemp(prefix="gl-il-bridge-")
        try:
            os.environ["AGENT_BRIDGE_DIR"] = tmpdir
            with mock.patch.object(authority, "verify_authority",
                                    return_value=signed_failed), \
                 mock.patch.object(authority, "verify_task_scope",
                                    return_value={"ok": True,
                                                  "status": "INTERACTIVE_LOCAL",
                                                  "payload": ts_payload,
                                                  "authority_id": ts_payload["authority_id"],
                                                  "path": "/x",
                                                  "missing": [],
                                                  "head_sha": "",
                                                  "detail": "task-scope"}), \
                 mock.patch.object(runtime_loop.subprocess, "run",
                                    side_effect=_git_run_factory(ALT_BRANCH)):
                out = runtime_loop.builder_handoff(
                    "AGE-IL", ALT_REPO, "42", "deadbeef" * 5, "BUILDER_FIXING", [],
                    policy=self._policy(), observed_branch=ALT_BRANCH,
                    observed_base=BASE, mode="interactive_local")
            self.assertTrue(out.get("ok"), msg=out)
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "status.json")))
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
            os.environ.pop("AGENT_BRIDGE_DIR", None)


# ------------------------------------------------------------ #
# D. cmd_setup_task_scope : real stdin YES, spaces allowed     #
# ------------------------------------------------------------ #


class SetupTaskScopeCLITests(_TaskScopeHome):
    class _CaptureStdout:
        """Pretend to be a TTY so the CLI sees isatty()==True, while still
        capturing every write() into an inner StringIO. Avoids the
        ``redirect_stdout`` interaction, which would re-bind ``sys.stdout``
        to a StringIO whose isatty() returns False (silently turning every
        test into the INTERACTIVE_TERMINAL_REQUIRED branch)."""

        def __init__(self):
            self._buf = io.StringIO()
            self._is_tty = True

        def write(self, s):
            self._buf.write(s)

        def isatty(self):
            return True

        def flush(self):
            pass

        def drain(self) -> str:
            return self._buf.getvalue()

    def _setup_args(self, **overrides):
        values = dict(
            task_id="AGE-IL", repo=ALT_REPO, branch=ALT_BRANCH,
            baseline_sha=BASE, head_sha=HEAD_PIN,
            authority_id=None,
            allow_path=["tools/"], operation=None,
            trusted_reviewer=["trusted-reviewer"],
            replace=False,
        )
        values.update(overrides)
        return argparse.Namespace(**values)

    @staticmethod
    def _last_json(buffer):
        decoder = json.JSONDecoder()
        pos = 0
        last = None
        while pos < len(buffer):
            next_brace = buffer.find("{", pos)
            if next_brace < 0:
                break
            try:
                obj, end = decoder.raw_decode(buffer[next_brace:])
            except json.JSONDecodeError:
                break
            last = obj
            pos = next_brace + end
        return last

    def _invoke(self, args, stdin_text):
        from governloop_runtime.__main__ import cmd_setup_task_scope
        fake_out = self._CaptureStdout()
        reply = stdin_text if stdin_text.endswith("\n") else stdin_text + "\n"
        real_stdout = sys.stdout
        sys.stdout = fake_out
        try:
            with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(sys.stdin, "readline", return_value=reply):
                rc = cmd_setup_task_scope(args)
        finally:
            sys.stdout = real_stdout
        drained = fake_out.drain()
        last = self._last_json(drained)
        if last is None:
            self.fail("no JSON object in CLI output: " + repr(drained[:200]))
        return rc, last

    def test_lowercase_y_rejects(self):
        rc, result = self._invoke(self._setup_args(), "y")
        self.assertEqual(rc, 6)
        self.assertEqual(result.get("status"), "APPROVAL_MISMATCH")
        self.assertFalse(os.path.exists(self._record_path("AGE-IL")))

    def test_lowercase_yes_rejects(self):
        rc, result = self._invoke(self._setup_args(), "yes")
        self.assertEqual(rc, 6)
        self.assertEqual(result.get("status"), "APPROVAL_MISMATCH")

    def test_uppercase_YES_with_surrounding_whitespace_writes_file(self):
        # User pinned readline().strip() == "YES" with spaces allowed around.
        rc, result = self._invoke(self._setup_args(), "  YES  ")
        self.assertEqual(rc, 0)
        self.assertEqual(result.get("status"), "TASK_SCOPE_CONFIRMED")
        self.assertEqual(result["mode"], "interactive_local")
        target = self._record_path("AGE-IL")
        self.assertTrue(os.path.isfile(target))
        with open(target) as f:
            payload = json.load(f)
        self.assertEqual(payload["confirmation_method"], "interactive_local_tty_yes")
        self.assertTrue(payload["integrity_sha256"])  # presence + non-empty

    def test_uppercase_YES_alone_writes_file(self):
        rc, result = self._invoke(self._setup_args(), "YES")
        self.assertEqual(rc, 0)
        self.assertEqual(result.get("status"), "TASK_SCOPE_CONFIRMED")

    def test_non_tty_blocks_before_writing(self):
        from governloop_runtime.__main__ import cmd_setup_task_scope
        fake_out = self._CaptureStdout()
        # Make sys.stdout.isatty() report False, but the CLI uses a freshly
        # captured stdout that is TTY-shaped — only the CLI's *check* counts
        # when re-bound, so instead patch sys.stdout itself to a non-TTY
        # wrapper that delegates writes to fake_out.
        class _NonTtyOut:
            def __init__(self, sink):
                self._sink = sink
            def write(self, s):
                fake_out._buf.write(s)
            def isatty(self):
                return False
            def flush(self):
                pass
        real_stdout = sys.stdout
        sys.stdout = _NonTtyOut(fake_out)
        try:
            with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(sys.stdin, "readline") as rl:
                rc = cmd_setup_task_scope(self._setup_args())
        finally:
            sys.stdout = real_stdout
        rl.assert_not_called()
        result = json.loads(fake_out.drain())
        self.assertEqual(rc, 6)
        self.assertEqual(result.get("status"), "INTERACTIVE_TERMINAL_REQUIRED")

    def test_lifecycle_op_rejected_at_render_time(self):
        from governloop_runtime.__main__ import cmd_setup_task_scope
        fake_out = self._CaptureStdout()
        real_stdout = sys.stdout
        sys.stdout = fake_out
        try:
            with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(sys.stdin, "readline",
                                    return_value="YES\n"):
                rc = cmd_setup_task_scope(
                    self._setup_args(operation=["fix", "merge"]))
        finally:
            sys.stdout = real_stdout
        self.assertEqual(rc, 2)
        result = json.loads(fake_out.drain())
        self.assertEqual(result.get("status"), "INVALID_REQUEST")
        self.assertIn("lifecycle", result.get("detail", ""))

    def test_existing_file_blocked_without_replace(self):
        from governloop_runtime.__main__ import cmd_setup_task_scope
        self._write("AGE-IL", _task_scope_payload())
        fake_out = self._CaptureStdout()
        real_stdout = sys.stdout
        sys.stdout = fake_out
        try:
            with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(sys.stdin, "readline", return_value="YES\n"):
                rc = cmd_setup_task_scope(self._setup_args())
        finally:
            sys.stdout = real_stdout
        result = json.loads(fake_out.drain())
        self.assertEqual(rc, 0)
        self.assertEqual(result.get("status"), "TASK_SCOPE_EXISTS")
        with open(self._record_path("AGE-IL")) as f:
            data = json.load(f)
        self.assertEqual(data["branch"], ALT_BRANCH)

    def test_replace_with_lowercase_still_rejected(self):
        from governloop_runtime.__main__ import cmd_setup_task_scope
        self._write("AGE-IL", _task_scope_payload(branch="feat/old"))
        fake_out = self._CaptureStdout()
        real_stdout = sys.stdout
        sys.stdout = fake_out
        try:
            with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(sys.stdin, "readline", return_value="yes\n"):
                rc = cmd_setup_task_scope(self._setup_args(replace=True))
        finally:
            sys.stdout = real_stdout
        self.assertEqual(rc, 6)
        with open(self._record_path("AGE-IL")) as f:
            data = json.load(f)
        self.assertEqual(data["branch"], "feat/old")

    def test_replace_with_yes_overwrites(self):
        from governloop_runtime.__main__ import cmd_setup_task_scope
        self._write("AGE-IL", _task_scope_payload(branch="feat/old"))
        fake_out = self._CaptureStdout()
        real_stdout = sys.stdout
        sys.stdout = fake_out
        try:
            with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(sys.stdin, "readline", return_value="YES\n"):
                rc = cmd_setup_task_scope(
                    self._setup_args(replace=True, branch="feat/new"))
        finally:
            sys.stdout = real_stdout
        self.assertEqual(rc, 0, msg=fake_out.drain())
        with open(self._record_path("AGE-IL")) as f:
            data = json.load(f)
        self.assertEqual(data["branch"], "feat/new")


# --------------------------------------------------- #
# E. CLI surface / signature smoke tests              #
# --------------------------------------------------- #


class SurfaceTests(unittest.TestCase):
    def test_builder_handoff_signature_carries_mode(self):
        from agentops_runtime import runtime_loop
        sig = inspect.signature(runtime_loop.builder_handoff)
        self.assertIn("mode", sig.parameters)
        self.assertIs(sig.parameters["mode"].default, None)

    def test_verified_scope_policy_signature_carries_mode(self):
        from agentops_runtime import runtime_loop
        sig = inspect.signature(runtime_loop._verified_scope_policy)
        self.assertIn("mode", sig.parameters)
        self.assertEqual(sig.parameters["mode"].default, "signed")

    def test_apply_verified_authority_signature_carries_mode(self):
        from governloop_runtime import authority
        sig = inspect.signature(authority.apply_verified_authority)
        self.assertIn("mode", sig.parameters)
        self.assertEqual(sig.parameters["mode"].default, "signed")

    def test_configure_process_signature_carries_mode(self):
        from governloop_runtime import _compat
        sig = inspect.signature(_compat.configure_process)
        self.assertIn("mode", sig.parameters)
        self.assertEqual(sig.parameters["mode"].default, "signed")

    def test_parser_exposes_new_subcommands(self):
        from governloop_runtime.__main__ import build_parser
        parser = build_parser()
        a = parser.parse_args(
            ["setup-task-scope", "--task-id", "X", "--repo", "o/r", "--branch",
             "b", "--baseline-sha", BASE, "--allow-path", "tools",
             "--trusted-reviewer", "r"])
        self.assertEqual(a.command, "setup-task-scope")
        b = parser.parse_args(
            ["interactive-local", "--task-id", "X", "--repo", "o/r", "--pr", "1"])
        self.assertEqual(b.command, "interactive-local")
        c = parser.parse_args(["task-scope-check", "--task-id", "X"])
        self.assertEqual(c.command, "task-scope-check")


if __name__ == "__main__":
    unittest.main()
