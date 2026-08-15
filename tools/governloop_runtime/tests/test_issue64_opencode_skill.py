import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _TOOLS)

from governloop_runtime import cli, opencode_skill


class TestIssue64OpenCodeSkill(unittest.TestCase):
    def test_canonical_skill_has_valid_opencode_frontmatter(self):
        text = opencode_skill.canonical_skill_text()
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("\nname: governloop\n", text)
        self.assertIn("\ndescription:", text)
        self.assertIn("--host-confirm", text)
        self.assertIn("Ready, Merge, Release, Deploy", text)
        self.assertIn("correct project", text)

    def test_install_writes_only_requested_skill_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / ".config/opencode/skills/governloop/SKILL.md"
            global_agents = root / ".config/opencode/AGENTS.md"
            global_agents.parent.mkdir(parents=True, exist_ok=True)
            global_agents.write_text("keep me\n", encoding="utf-8")

            result = opencode_skill.install(target=target)

            self.assertEqual(result["status"], "OPENCODE_SKILL_INSTALLED")
            self.assertEqual(result["skill"], "governloop")
            self.assertFalse(result["global_agents_modified"])
            self.assertEqual(target.read_text(encoding="utf-8"), opencode_skill.canonical_skill_text())
            self.assertEqual(global_agents.read_text(encoding="utf-8"), "keep me\n")

    def test_install_updates_existing_skill(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "SKILL.md"
            target.write_text("old\n", encoding="utf-8")
            opencode_skill.install(target=target)
            self.assertEqual(target.read_text(encoding="utf-8"), opencode_skill.canonical_skill_text())

    def test_cli_routes_install_command_without_runtime_parser(self):
        with mock.patch.object(opencode_skill, "main", return_value=0) as install_main, \
             mock.patch.object(cli.runtime_cli, "main") as runtime_main:
            rc = cli.main(["install-opencode-skill"])
        self.assertEqual(rc, 0)
        install_main.assert_called_once_with([])
        runtime_main.assert_not_called()

    def test_top_level_help_advertises_skill_installer(self):
        out = io.StringIO()
        with mock.patch.object(cli.runtime_cli, "main") as runtime_main, \
             contextlib.redirect_stdout(out):
            rc = cli.main([])
        self.assertEqual(rc, 0)
        runtime_main.assert_not_called()
        self.assertIn("governloop install-opencode-skill", out.getvalue())


if __name__ == "__main__":
    unittest.main()
