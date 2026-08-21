import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import governloop_session as gl


def make_git_repo(dirpath, origin_url=None, branch="main"):
    os.makedirs(dirpath, exist_ok=True)
    subprocess.run(["git", "-C", dirpath, "init", "-q", "-b", branch], check=True,
                   capture_output=True)
    # initial commit so HEAD resolves (also exercises real-repo behavior)
    open(os.path.join(dirpath, "README.md"), "w").write("# repo\n")
    subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", "init"], check=True,
                   capture_output=True)
    if origin_url:
        subprocess.run(["git", "-C", dirpath, "remote", "add", "origin", origin_url],
                       check=True, capture_output=True)
    return dirpath


class TestRepoDetection(unittest.TestCase):
    def test_remote_url_to_slug_https(self):
        self.assertEqual(gl.remote_url_to_slug("https://github.com/owner/repo.git"),
                         "owner/repo")
        self.assertEqual(gl.remote_url_to_slug("https://github.com/owner/repo"),
                         "owner/repo")

    def test_remote_url_to_slug_ssh(self):
        self.assertEqual(gl.remote_url_to_slug("git@github.com:owner/repo.git"),
                         "owner/repo")
        self.assertEqual(gl.remote_url_to_slug("ssh://git@github.com/owner/repo.git"),
                         "owner/repo")

    def test_detect_repo_from_origin(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_git_repo(td, origin_url="https://github.com/acme/widget.git")
            self.assertEqual(gl.detect_repo(td), "acme/widget")

    def test_detect_repo_falls_back_to_dir_name(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_git_repo(td)  # no origin
            self.assertEqual(gl.detect_repo(td), os.path.basename(td))


class TestTaskDetection(unittest.TestCase):
    def test_env_issue_id_wins_over_branch_and_title(self):
        with tempfile.TemporaryDirectory() as td:
            make_git_repo(td, branch="docs/whatever-123")
            env = {"LINEAR_ISSUE_ID": "LEA-42"}
            task, src = gl.detect_task(cwd=td, title="Some Title", env=env)
            self.assertEqual(task, "LEA-42")
            self.assertEqual(src, "env:LINEAR_ISSUE_ID")

    def test_branch_wins_over_title(self):
        with tempfile.TemporaryDirectory() as td:
            make_git_repo(td, branch="feature/issue-128-cursor-pull")
            task, src = gl.detect_task(cwd=td, title="My Title", env={})
            self.assertEqual(task, "ISSUE-128")
            self.assertEqual(src, "branch")

    def test_branch_issue_token(self):
        with tempfile.TemporaryDirectory() as td:
            make_git_repo(td, branch="docs/LEA-91-acceptance")
            task, src = gl.detect_task(cwd=td, title="ignored", env={})
            self.assertEqual(task, "LEA-91")
            self.assertEqual(src, "branch")

    def test_title_falls_back_to_slug(self):
        with tempfile.TemporaryDirectory() as td:
            make_git_repo(td, branch="main")
            task, src = gl.detect_task(cwd=td, title="Fix Login Flow", env={})
            self.assertEqual(task, "FIX-LOGIN-FLOW")
            self.assertEqual(src, "title")

    def test_slug_when_nothing_available(self):
        with tempfile.TemporaryDirectory() as td:
            make_git_repo(td, branch="main")
            task, src = gl.detect_task(cwd=td, title=None, env={})
            self.assertTrue(task.startswith("TASK-"))
            self.assertEqual(src, "slug")


class TestSessionIdentity(unittest.TestCase):
    def test_session_id_auto_generated_no_manual_session(self):
        # user never has to invent a SESSION ID
        sid = gl.session_id_for("Widget", "LEA-42", date="2026-08-21")
        self.assertEqual(sid, "WIDGET-LEA-42-2026-08-21")
        self.assertIn("2026-08-21", sid)

    def test_same_session_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_git_repo(td, origin_url="https://github.com/acme/widget.git",
                                 branch="feature/LEA-42")
            state1, created1, _ = gl.new_session(td, cwd=repo)
            state2, created2, _ = gl.new_session(td, cwd=repo)
            self.assertEqual(state1["session_id"], state2["session_id"])
            self.assertFalse(created1)  # first = NEW
            self.assertTrue(created2)   # second = REUSE
            files = [f for f in os.listdir(td) if f.startswith("governloop-session-")]
            self.assertEqual(len(files), 1)  # no duplicate state

    def test_cross_repo_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            r1 = make_git_repo(os.path.join(td, "a"), "https://github.com/acme/alpha.git",
                               branch="feature/LEA-1")
            r2 = make_git_repo(os.path.join(td, "b"), "https://github.com/acme/beta.git",
                               branch="feature/LEA-1")
            s1, _, _ = gl.new_session(td, cwd=r1)
            s2, _, _ = gl.new_session(td, cwd=r2)
            self.assertNotEqual(s1["session_id"], s2["session_id"])

    def test_new_session_does_not_inherit_prior_url(self):
        with tempfile.TemporaryDirectory() as td:
            r1 = make_git_repo(os.path.join(td, "a"), "https://github.com/acme/alpha.git",
                               branch="feature/LEA-1")
            r2 = make_git_repo(os.path.join(td, "b"), "https://github.com/acme/beta.git",
                               branch="feature/LEA-1")
            s1, _, _ = gl.new_session(td, cwd=r1)
            gl.bind_url(td, s1["session_id"], "https://chatgpt.com/c/abc-123")
            s2, _, _ = gl.new_session(td, cwd=r2)
            self.assertIsNone(s2.get("conversation_url"))  # isolated


class TestBindAndRequirement(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.repo = make_git_repo(self.td.name, "https://github.com/acme/widget.git",
                                  branch="feature/LEA-42")

    def tearDown(self):
        self.td.cleanup()

    def test_missing_url_returns_user_conversation_selection_required(self):
        state, created, _ = gl.new_session(self.td.name, cwd=self.repo)
        self.assertIsNone(state.get("conversation_url"))
        # checkpoint without bind -> USER_CONVERSATION_SELECTION_REQUIRED (exit 3)
        ok, text, code = gl.run_checkpoint(self.td.name, cwd=self.repo, ctype="REVIEW_REQUIRED",
                                           state=state)
        self.assertFalse(ok)
        self.assertEqual(code, 3)
        self.assertIn(gl.USER_CONVERSATION_SELECTION_REQUIRED, text)

    def test_bind_stores_url_in_temp_state_only(self):
        state, _, _ = gl.new_session(self.td.name, cwd=self.repo)
        url = "https://chatgpt.com/c/6a82b993-f1e0-83ec-9cba-b77ec91e572f"
        state2, msg = gl.bind_url(self.td.name, state["session_id"], url)
        self.assertEqual(state2["conversation_url"], url)
        self.assertIn("canonical config untouched", msg)
        # canonical config must never be modified by the skill
        if os.path.exists(gl.CANONICAL_CONFIG):
            d = json.load(open(gl.CANONICAL_CONFIG, encoding="utf-8"))
            route = d.get("routes", {}).get("acme/widget", {})
            self.assertIsNone(route.get("conversation_url", None))

    def test_bind_rejects_non_conversation_url(self):
        state, _, _ = gl.new_session(self.td.name, cwd=self.repo)
        s, msg = gl.bind_url(self.td.name, state["session_id"], "https://example.com/not-chat")
        self.assertIsNone(s)
        self.assertIn("not a valid ChatGPT conversation URL", msg)

    def test_session_cleanup_removes_temp_state(self):
        state, _, _ = gl.new_session(self.td.name, cwd=self.repo)
        p = gl.state_path(self.td.name, state["session_id"])
        self.assertTrue(os.path.exists(p))
        ok, text, code = gl.end_session(self.td.name, state["session_id"], send_final=False)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(p))
        self.assertIn("canonical config untouched", text)


class TestCheckpointDelivery(unittest.TestCase):
    def _stub_relay(self, td):
        """A stub relay that records argv and writes a canned response."""
        stub = os.path.join(td, "stub_relay.py")
        argv_out = os.path.join(td, "stub-argv.json")
        with open(stub, "w") as f:
            f.write(
                "import json, sys\n"
                "args = sys.argv[1:]\n"
                f"open({argv_out!r},'w').write(json.dumps(args))\n"
                "out = args[args.index('--output-file')+1]\n"
                "open(out,'w').write('DECISION: PROCEED\\nBLOCKER: NONE\\n')\n"
                "print('Success: Wrote response to ' + out)\n"
            )
        return stub, argv_out

    def test_checkpoint_sends_text_and_attachments_to_same_session(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_git_repo(td, "https://github.com/acme/widget.git",
                                 branch="feature/LEA-42")
            state, _, _ = gl.new_session(td, cwd=repo)
            gl.bind_url(td, state["session_id"], "https://chatgpt.com/c/abc-123")
            ev = os.path.join(td, "evidence.md")
            with open(ev, "w") as f:
                f.write("# evidence\nNO P0/P1\n")
            stub, argv_out = self._stub_relay(td)
            ok, text, code = gl.run_checkpoint(
                td, cwd=repo, ctype="BEFORE_DESTRUCTIVE_ACTION",
                message="about to retire", attach=[ev], relay_path=stub,
            )
            self.assertTrue(ok, text)
            self.assertEqual(code, 0)
            self.assertIn("TEXT_RELAY: PASS", text)
            self.assertIn("ATTACHMENTS: 1 delivered", text)
            # relay was called with the request file + attachment + temp config
            argv = json.load(open(argv_out))
            self.assertIn("--attachment", argv)
            self.assertIn(ev, argv)
            self.assertIn("--config-file", argv)
            # request file contains required relay routing fields
            req = argv[argv.index("--request-file") + 1]
            body = open(req).read()
            self.assertIn("REVIEW_REQUEST_ID:", body)
            self.assertIn("REPO: acme/widget", body)
            self.assertIn("CHECKPOINT: BEFORE_DESTRUCTIVE_ACTION", body)
            self.assertIn("SESSION: " + state["session_id"], body)
            # state recorded the checkpoint (reload from disk — run_checkpoint
            # updates the persisted session state)
            persisted = gl.load_state(td, state["session_id"])
            self.assertEqual(len(persisted["checkpoints"]), 1)
            self.assertEqual(persisted["checkpoints"][0]["type"],
                             "BEFORE_DESTRUCTIVE_ACTION")

    def test_checkpoint_secret_attachment_refused_no_relay(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_git_repo(td, "https://github.com/acme/widget.git",
                                 branch="feature/LEA-42")
            state, _, _ = gl.new_session(td, cwd=repo)
            gl.bind_url(td, state["session_id"], "https://chatgpt.com/c/abc-123")
            leak = os.path.join(td, "leak.md")
            with open(leak, "w") as f:
                f.write("token: ghp_1234567890abcdefghijklmnop\n")
            stub, argv_out = self._stub_relay(td)
            ok, text, code = gl.run_checkpoint(
                td, cwd=repo, ctype="REVIEW_REQUIRED", attach=[leak], relay_path=stub,
            )
            self.assertFalse(ok)
            self.assertEqual(code, 1)
            self.assertIn("CHECKPOINT_DELIVERY_INCOMPLETE", text)
            self.assertIn("redacted", text)
            self.assertFalse(os.path.exists(argv_out))  # relay never called

    def test_checkpoint_missing_attachment_refused(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_git_repo(td, "https://github.com/acme/widget.git",
                                 branch="feature/LEA-42")
            state, _, _ = gl.new_session(td, cwd=repo)
            gl.bind_url(td, state["session_id"], "https://chatgpt.com/c/abc-123")
            ok, text, code = gl.run_checkpoint(
                td, cwd=repo, ctype="FINAL_VERIFICATION", attach=["/no/such/file.md"],
                relay_path=self._stub_relay(td)[0],
            )
            self.assertFalse(ok)
            self.assertIn("missing", text)

    def test_final_verification_requires_state_and_sends(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_git_repo(td, "https://github.com/acme/widget.git",
                                 branch="feature/LEA-42")
            state, _, _ = gl.new_session(td, cwd=repo)
            gl.bind_url(td, state["session_id"], "https://chatgpt.com/c/abc-123")
            stub, argv_out = self._stub_relay(td)
            ok, text, code = gl.end_session(
                td, state["session_id"], send_final=True, relay_path=stub,
            )
            self.assertTrue(ok)
            self.assertIn("ENDED", text)
            self.assertFalse(os.path.exists(gl.state_path(td, state["session_id"])))
            argv = json.load(open(argv_out))
            req = open(argv[argv.index("--request-file") + 1]).read()
            self.assertIn("CHECKPOINT: FINAL_VERIFICATION", req)


if __name__ == "__main__":
    unittest.main()
