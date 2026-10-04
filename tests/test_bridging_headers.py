"""Healthy projects first, followed by isolated header defects."""

from pathlib import Path
import unittest

from _support import cli_json, make_tree


class BridgingHeaderTests(unittest.TestCase):
    def test_multiple_projects_health_then_nested_defect(self):
        files = {
            "one/App.xcodeproj/project.pbxproj": 'SWIFT_OBJC_BRIDGING_HEADER = "App/Bridge.h";',
            "one/App/Bridge.h": "// healthy\n",
            "two/App.xcodeproj/project.pbxproj": 'SWIFT_OBJC_BRIDGING_HEADER = "${PROJECT_DIR}/App/Bridge.h";',
            "two/App/Bridge.h": "/*\n#pragma once\n*/\nconst char *url = \"https://example.org\";\n",
            "two/App/Ordinary.h": "#pragma once\n",
        }
        with make_tree(files) as temp:
            code, report = cli_json(temp, "--strict", "--check", "apple.bridging_header_pragma_once")
            self.assertEqual(code, 0)
            self.assertEqual(report["results"][0]["units_examined"], 2)
            Path(temp, "two/App/Bridge.h").write_text(files["two/App/Bridge.h"] + "#pragma once\n")
            code, report = cli_json(temp, "--strict", "--check", "apple.bridging_header_pragma_once")
            self.assertEqual(code, 1)
            findings = report["results"][0]["findings"]
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["file"], "two/App/Bridge.h")
            self.assertEqual(findings[0]["line"], 5)

    def test_excluded_header_is_unmeasured(self):
        files = {
            ".ruttla.toml": 'config_version = 1\n[gate]\nexclude = ["App/**"]\n',
            "App.xcodeproj/project.pbxproj": 'SWIFT_OBJC_BRIDGING_HEADER = "App/Bridge.h";',
            "App/Bridge.h": "#pragma once\n",
        }
        with make_tree(files) as temp:
            _, report = cli_json(temp, "--check", "apple.bridging_header_pragma_once")
        self.assertEqual(report["results"][0]["status"], "unmeasured")


if __name__ == "__main__":
    unittest.main()
