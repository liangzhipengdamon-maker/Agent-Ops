import unittest
import os
import sys

# Ensure scripts can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
import worktree_status


class TestPorcelainParsing(unittest.TestCase):

    def test_single_main_worktree(self):
        text = (
            "worktree /Users/u/GovernLoop-workspace/repos/GovernLoop\n"
            "HEAD 01c193aec7ad5120cfd102812a12d32594c68e85\n"
            "branch refs/heads/main\n"
        )
        worktrees = worktree_status.parse_porcelain(text)
        self.assertEqual(len(worktrees), 1)
        self.assertEqual(
            worktrees[0]["path"],
            "/Users/u/GovernLoop-workspace/repos/GovernLoop",
        )
        self.assertEqual(
            worktrees[0]["head"],
            "01c193aec7ad5120cfd102812a12d32594c68e85",
        )
        self.assertEqual(worktrees[0]["branch"], "refs/heads/main")

    def test_multiple_worktrees(self):
        text = (
            "worktree /Users/u/GovernLoop-workspace/repos/GovernLoop\n"
            "HEAD 01c193aec7ad5120cfd102812a12d32594c68e85\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /Users/u/GovernLoop-workspace/worktrees/issue-84\n"
            "HEAD deadbeefcafebabec0ffee123456789abcdef0123\n"
            "branch refs/heads/issue-84\n"
        )
        worktrees = worktree_status.parse_porcelain(text)
        self.assertEqual(len(worktrees), 2)
        self.assertEqual(worktrees[1]["branch"], "refs/heads/issue-84")
        self.assertEqual(worktrees[1]["head"], "deadbeefcafebabec0ffee123456789abcdef0123")

    def test_detached_head_has_no_branch(self):
        text = (
            "worktree /Users/u/GovernLoop-workspace/worktrees/review-pr-85\n"
            "HEAD 5aa5aa5aa5aa5aa5aa5aa5aa5aa5aa5aa5aa5aa5a\n"
        )
        worktrees = worktree_status.parse_porcelain(text)
        self.assertEqual(len(worktrees), 1)
        self.assertIsNone(worktrees[0]["branch"])

    def test_empty_input_returns_no_worktrees(self):
        self.assertEqual(worktree_status.parse_porcelain(""), [])

    def test_has_tracked_changes_ignores_untracked_only(self):
        self.assertFalse(
            worktree_status.has_tracked_changes(["?? .workbuddy/", "?? scratch.txt"])
        )

    def test_has_tracked_changes_detects_modified(self):
        self.assertTrue(
            worktree_status.has_tracked_changes([" M scripts/worktree_status.py"])
        )

    def test_has_tracked_changes_detects_staged(self):
        self.assertTrue(
            worktree_status.has_tracked_changes(["A  scripts/worktree_status.py"])
        )

    def test_has_tracked_changes_empty_is_clean(self):
        self.assertFalse(worktree_status.has_tracked_changes([]))

    def test_fmt_head_shortens_and_handles_none(self):
        self.assertEqual(
            worktree_status.fmt_head("01c193aec7ad5120cfd102812a12d32594c68e85"),
            "01c193aec7ad",
        )
        self.assertEqual(worktree_status.fmt_head(None), "(none)")


if __name__ == "__main__":
    unittest.main()
