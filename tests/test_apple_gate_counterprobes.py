"""Effective parent ignore policy and old/new generator argument boundaries."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from _support import cli_json, make_tree


class AppleGateCounterprobes(unittest.TestCase):
    def test_parent_gitignore_health_then_isolated_negation(self):
        files = {".gitignore": "xcuserdata/\n*.xcuserstate\n",
                 "game/App.xcodeproj/project.pbxproj": "// project\n"}
        with make_tree(files) as temp:
            result = subprocess.run(["git", "init", "-q", temp], capture_output=True)
            self.assertEqual(result.returncode, 0)
            code, report = cli_json(str(Path(temp, "game")), "--strict", "--check", "apple.gitignore_xcode_user_data")
            self.assertEqual(code, 0)
            self.assertEqual(report["results"][0]["status"], "pass")
            Path(temp, "game/.gitignore").write_text("!*.xcuserstate\n")
            code, report = cli_json(str(Path(temp, "game")), "--strict", "--check", "apple.gitignore_xcode_user_data")
            self.assertEqual(code, 1)
            self.assertEqual(report["blocking_findings"], 1)

    def test_unrelated_ignore_file_cannot_protect_other_project(self):
        files = {".gitignore": "*.log\n", "other/.gitignore": "xcuserdata/\n*.xcuserstate\n",
                 "game/App.xcodeproj/project.pbxproj": "// project\n"}
        with make_tree(files) as temp:
            subprocess.run(["git", "init", "-q", temp], check=True, capture_output=True)
            code, report = cli_json(temp, "--strict", "--check", "apple.gitignore_xcode_user_data")
        self.assertEqual(code, 1)
        self.assertEqual(report["blocking_findings"], 1)

    def test_multiline_unicode_old_argument_then_broken_replacement(self):
        code = 'caption = "ÄÖÜ"; content = content.replace(\n    "LastUpgradeCheck = 0500;",\n    "LastUpgradeCheck = 2700;",\n)\n'
        with make_tree({"tools/patch.py": code}) as temp:
            result, report = cli_json(temp, "--check", "apple.project_generator_outdated")
            self.assertEqual(result, 0)
            self.assertEqual(report["results"][0]["status"], "pass")
            Path(temp, "tools/patch.py").write_text(code.replace('2700', '0500'))
            result, report = cli_json(temp, "--check", "apple.project_generator_outdated")
            self.assertEqual(report["results"][0]["status"], "fail")
            self.assertEqual(len(report["results"][0]["findings"]), 1)


if __name__ == "__main__":
    unittest.main()
