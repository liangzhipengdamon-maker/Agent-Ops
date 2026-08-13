import os
import tempfile
import unittest
from pathlib import Path

from agentops_runtime.scope_firewall import _is_path_allowed


class ExternalPathScopeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.root = self.base / "authorized"
        self.root.mkdir()
        self.sibling = self.base / "sibling"
        self.sibling.mkdir()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_existing_relative_repo_scope_is_unchanged(self):
        self.assertTrue(_is_path_allowed("tools/file.py", ("tools",)))
        self.assertFalse(_is_path_allowed("docs/file.md", ("tools",)))

    def test_absolute_path_stays_blocked_without_explicit_absolute_root(self):
        self.assertFalse(_is_path_allowed(str(self.root / "file.txt"), ("tools",)))

    def test_explicit_absolute_root_allows_itself_and_descendants(self):
        allowed = (str(self.root),)
        self.assertTrue(_is_path_allowed(str(self.root), allowed))
        self.assertTrue(_is_path_allowed(str(self.root / "file.txt"), allowed))

    def test_allowed_absolute_root_itself_cannot_be_symlink(self):
        link = self.base / "authorized-link"
        link.symlink_to(self.root, target_is_directory=True)
        self.assertFalse(_is_path_allowed(str(self.root / "file.txt"), (str(link),)))

    def test_retargeted_allowed_root_symlink_stays_blocked(self):
        link = self.base / "authorized-link"
        link.symlink_to(self.root, target_is_directory=True)
        self.assertFalse(_is_path_allowed(str(self.root / "file.txt"), (str(link),)))
        link.unlink()
        link.symlink_to(self.sibling, target_is_directory=True)
        self.assertFalse(_is_path_allowed(str(self.sibling / "file.txt"), (str(link),)))

    def test_sibling_escape_is_blocked(self):
        self.assertFalse(_is_path_allowed(str(self.sibling / "file.txt"), (str(self.root),)))

    def test_raw_traversal_is_blocked(self):
        target = str(self.root / ".." / "sibling" / "file.txt")
        self.assertFalse(_is_path_allowed(target, (str(self.root),)))

    def test_symlink_escape_is_blocked(self):
        link = self.root / "outside"
        link.symlink_to(self.sibling, target_is_directory=True)
        self.assertFalse(_is_path_allowed(str(link / "file.txt"), (str(self.root),)))

    def test_filesystem_root_cannot_be_granted(self):
        self.assertFalse(_is_path_allowed(str(self.root / "file.txt"), (os.path.abspath(os.sep),)))


if __name__ == "__main__":
    unittest.main()
