"""Git inventory: healthy controls precede isolated defects, in both engines.

The oracle is real Git, not another ignore-pattern implementation. All writes
are confined to temporary synthetic repositories; no target code is executed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import cli, cli_json, ensure_checks_loaded, require_engine
from test_engine_inventory import engine_diff

from ruttla.config import Config
from ruttla.context import Context

ensure_checks_loaded()


@unittest.skipUnless(shutil.which("git"), "real Git required")
class GitInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.config = Config()
        self.config.brand_names = ["Acme"]
        self.write("src/Main.swift", 'Text(Brand.name)\n')

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args],
                              capture_output=True, check=True).stdout

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def parity(self, root=None):
        root = str(root or self.root)
        a = engine_diff.python_inventory(root, self.config)
        b = engine_diff.engine_inventory(require_engine(self), root, self.config)
        self.assertEqual(a, b, engine_diff.diff(a, b))
        return {f["rel"] for f in a["files"]}, a["coverage"]

    def brand(self):
        from ruttla.checks.universal.brand import check_brand_hardcoded
        return check_brand_hardcoded(Context(str(self.root), self.config))

    def test_00_healthy_source_and_ignored_build(self):
        self.write(".gitignore", "output-preview/\n")
        self.write("output-preview/index.html", "<h1>Acme</h1>\n")
        paths, cov = self.parity()
        self.assertEqual(paths, {"src/Main.swift", ".gitignore"})
        self.assertEqual(cov["git_ignore_status"], "applied")
        self.assertEqual(cov["dirs_excluded_by_gitignore"], 1)
        self.assertEqual(self.brand().findings, [])

    def test_01_same_build_without_ignore_is_a_finding(self):
        self.write("output-preview/index.html", "<h1>Acme</h1>\n")
        paths, _ = self.parity()
        self.assertIn("output-preview/index.html", paths)
        self.assertEqual([f.file for f in self.brand().findings], ["output-preview/index.html"])

    def test_02_tracked_file_beats_ignored_parent_directory(self):
        self.write("output-preview/index.html", "<h1>Acme</h1>\n")
        self.git("add", "output-preview/index.html")
        self.write(".gitignore", "output-preview/\n")
        self.write("output-preview/ignored.html", "<h1>Acme</h1>\n")
        paths, cov = self.parity()
        self.assertIn("output-preview/index.html", paths)
        self.assertNotIn("output-preview/ignored.html", paths)
        self.assertEqual(cov["files_excluded_by_gitignore"], 1)
        self.assertEqual([f.file for f in self.brand().findings], ["output-preview/index.html"])

    def test_03_no_git_repository_keeps_legacy_inventory_and_findings(self):
        with tempfile.TemporaryDirectory() as plain:
            root = Path(plain)
            (root / ".gitignore").write_text("index.html\n")
            (root / "index.html").write_text("<h1>Acme</h1>\n")
            paths, cov = self.parity(root)
            self.assertIn("index.html", paths)
            self.assertEqual(cov["git_ignore_status"], "not_repository")
            from ruttla.checks.universal.brand import check_brand_hardcoded
            self.assertEqual(len(check_brand_hardcoded(Context(plain, self.config)).findings), 1)
            out = cli(plain, "--format", "agent", "--check", "brand.hardcoded_in_display")
            self.assertIn("GIT_IGNORE=not_repository", out.stdout)
            self.assertIn("bisherige Inventarausschlüsse", out.stdout)

    def test_04_missing_git_is_visible_and_keeps_files(self):
        self.write(".gitignore", "src/\n")
        with tempfile.TemporaryDirectory() as empty_path, mock.patch.dict(os.environ, {"PATH": empty_path}):
            paths, cov = self.parity()
            self.assertIn("src/Main.swift", paths)
            self.assertEqual(cov["git_ignore_status"], "git_unavailable")
            out = cli(str(self.root), "--check", "brand.hardcoded_in_display", "--format", "agent")
            self.assertIn("GIT_IGNORE=git_unavailable", out.stdout)
            self.assertIn("git nicht verfügbar", out.stdout)

    def test_05_nested_patterns_negation_and_scan_subdirectory(self):
        self.write(".gitignore", "*.generated.ts\n")
        self.write("pkg/.gitignore", "*.ts\n!keep.ts\n!parent.generated.ts\n")
        for name in ("skip.ts", "keep.ts", "parent.generated.ts", "sp ace.ts", "ä.ts", "line\nbreak.ts"):
            if os.name == "nt" and "\n" in name:
                continue
            self.write("pkg/" + name, "export const value = 1;\n")
        paths, _ = self.parity()
        self.assertIn("pkg/keep.ts", paths)
        self.assertIn("pkg/parent.generated.ts", paths)
        self.assertNotIn("pkg/skip.ts", paths)
        sub, cov = self.parity(self.root / "pkg")
        self.assertEqual(sub, {".gitignore", "keep.ts", "parent.generated.ts"})
        self.assertEqual(cov["git_ignore_status"], "applied")

    def test_06_standard_info_exclude_and_global_excludes(self):
        self.write(".git/info/exclude", "info.ts\n")
        with tempfile.TemporaryDirectory() as external:
            excludes = Path(external) / "ignore"
            excludes.write_text("global.ts\n")
            self.git("config", "core.excludesFile", str(excludes))
            for name in ("info.ts", "global.ts", "keep.ts"):
                self.write(name, "x\n")
            paths, cov = self.parity()
            self.assertNotIn("info.ts", paths)
            self.assertNotIn("global.ts", paths)
            self.assertIn("keep.ts", paths)
            self.assertEqual(cov["files_excluded_by_gitignore"], 2)

    def test_07_force_added_ignored_file_remains_in_inventory(self):
        self.write(".gitignore", "*.swift\n")
        self.git("add", "-f", "src/Main.swift")
        self.write("src/hidden.swift", "Text(Brand.name)\n")
        paths, _ = self.parity()
        self.assertIn("src/Main.swift", paths)
        self.assertNotIn("src/hidden.swift", paths)

    def test_08_ignored_whole_tree_preserves_tracked_descendant(self):
        self.write("deep/under/tree/real.ts", "x\n")
        self.git("add", "deep/under/tree/real.ts")
        self.write(".gitignore", "deep/\n")
        self.write("deep/other/hidden.ts", "x\n")
        paths, _ = self.parity()
        self.assertIn("deep/under/tree/real.ts", paths)
        self.assertNotIn("deep/other/hidden.ts", paths)

    def test_09_existing_config_agent_size_and_symlink_boundaries(self):
        self.write(".gitignore", "ignored.ts\n")
        self.write("ignored.ts", "x" * 500)
        self.write("HANDOVER.md", "# local\n")
        self.write("too-big.ts", "x" * 500)
        self.config.exclude_globs = ["src/*"]
        self.config.max_file_bytes = 100
        paths, cov = self.parity()
        self.assertEqual(paths, {".gitignore"})
        self.assertEqual(cov["files_skipped_total"], 1)
        self.assertEqual(cov["files_excluded_agent_instructions"], 1)
        self.assertEqual(cov["files_excluded_by_config"], 1)
        if os.name != "nt":
            (self.root / "escape.ts").symlink_to("/nonexistent-ruttla/outside.ts")
            a = engine_diff.python_inventory(str(self.root), self.config)
            b = engine_diff.engine_inventory(require_engine(self), str(self.root), self.config)
            self.assertEqual(a, b)
            self.assertEqual(a["error"]["kind"], "outside_root")

    def test_10_changed_only_retains_untracked_and_tracked_ignored_findings(self):
        self.write(".ruttla.toml", 'config_version = 1\n[brand]\nnames = ["Acme"]\n')
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "baseline")
        self.write(".gitignore", "output-preview/\nsrc/Main.swift\n")
        self.write("src/Main.swift", 'Text("Acme")\n')
        self.write("untracked.html", "<h1>Acme</h1>\n")
        self.write("output-preview/hidden.html", "<h1>Acme</h1>\n")
        code, report = cli_json(str(self.root), "--changed-only", "--strict", "--check", "brand.hardcoded_in_display")
        self.assertEqual(code, 1)
        self.assertEqual({f["file"] for f in report["results"][0]["findings"]},
                         {"src/Main.swift", "untracked.html"})

    def test_11_secret_view_and_existing_env_policy_survive(self):
        from ruttla.checks.universal.secrets import check_secrets
        token = "ghp_" + "a" * 36
        self.write(".gitignore", ".env\nprivate/\n")
        self.write(".env", "ACCESS=" + token + "\n")
        self.write("private/access.ts", "const key = process.env.ACCESS;\n")
        self.assertEqual(check_secrets(Context(str(self.root), self.config)).findings, [])
        self.write("private/access.ts", 'const key = "' + token + '";\n')
        ctx = Context(str(self.root), self.config)
        self.assertNotIn("private/access.ts", {f.rel for f in ctx.all_files()})
        self.assertEqual([f.file for f in check_secrets(ctx).findings], ["private/access.ts"])
        self.write(".gitignore", "private/\n")
        self.assertEqual({f.file for f in check_secrets(Context(str(self.root), self.config)).findings},
                         {"private/access.ts", ".env"})

    def test_12_ignored_nested_contract_and_sources_are_still_enforced(self):
        from ruttla.checks.universal.contracts import check_contract_expressions
        self.write(".gitignore", "local/\n")
        self.write("local/.ruttla-contracts.json", json.dumps({"version": 1, "expressions": [
            {"id": "amount", "source": "source.gd", "target": "AMOUNT",
             "cases": [{"inputs": {}, "expected": 30}]}]}))
        self.write("local/source.gd", "const AMOUNT = 30\n")
        self.assertEqual(check_contract_expressions(Context(str(self.root), self.config)).status.value, "pass")
        self.write("local/source.gd", "const AMOUNT = 25\n")
        self.assertEqual(check_contract_expressions(Context(str(self.root), self.config)).status.value, "fail")

    def test_13_referenced_ignored_bridging_header_is_still_measured(self):
        self.write("App.xcodeproj/project.pbxproj", 'SWIFT_OBJC_BRIDGING_HEADER = "local/Bridge.h";')
        self.write(".gitignore", "local/\n")
        self.write("local/Bridge.h", "#ifndef BRIDGE_H\n#define BRIDGE_H\n#endif\n")
        code, report = cli_json(str(self.root), "--strict", "--check", "apple.bridging_header_pragma_once")
        self.assertEqual(code, 0)
        self.assertEqual(report["results"][0]["units_examined"], 1)
        self.write("local/Bridge.h", "#pragma once\n")
        code, report = cli_json(str(self.root), "--strict", "--check", "apple.bridging_header_pragma_once")
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0]["findings"][0]["file"], "local/Bridge.h")

    def test_14_explicit_view_keeps_config_excludes(self):
        self.write(".gitignore", "private/\n")
        self.write("private/a.ts", "x\n")
        self.config.exclude_globs = ["private/*"]
        ctx = Context(str(self.root), self.config)
        self.assertNotIn("private/a.ts", {f.rel for f in ctx.including_gitignored().all_files()})
        self.assertIs(ctx.including_gitignored(), ctx.including_gitignored())

    def test_15_git_failure_is_visible_without_changing_legacy_behavior(self):
        self.write(".gitignore", "src/\n")
        self.write(".git/index", "not an index\n")
        paths, cov = self.parity()
        self.assertIn("src/Main.swift", paths)
        self.assertEqual(cov["git_ignore_status"], "git_error")

    def test_16_git_repository_redirects_cannot_change_the_target(self):
        with tempfile.TemporaryDirectory() as other:
            self.write(".gitignore", "src/\n")
            with mock.patch.dict(os.environ, {"GIT_DIR": other, "GIT_WORK_TREE": other,
                                              "GIT_INDEX_FILE": str(Path(other) / "index")}):
                paths, cov = self.parity()
                self.assertNotIn("src/Main.swift", paths)
                self.assertEqual(cov["git_ignore_status"], "applied")

    def test_17_git_fsmonitor_hook_is_not_executed(self):
        if os.name == "nt":
            self.skipTest("executable shell hook requires POSIX")
        hook = self.write(".git/monitor", "#!/bin/sh\ntouch \"" + str(self.root / "executed") + "\"\n")
        hook.chmod(0o755)
        self.git("config", "core.fsmonitor", str(hook))
        self.parity()
        self.assertFalse((self.root / "executed").exists())

    def test_18_runtime_receipt_in_ignored_tree_remains_mandatory(self):
        from ruttla.checks.universal.contracts import _proof_files, check_contract_runtime_evidence
        for rel, content in _proof_files().items():
            self.write("local/" + rel, content)
        self.write(".gitignore", "local/\n")
        self.assertEqual(check_contract_runtime_evidence(Context(str(self.root), self.config)).status.value, "pass")
        (self.root / "local/.test-evidence.json").unlink()
        self.assertEqual(check_contract_runtime_evidence(Context(str(self.root), self.config)).status.value, "fail")

    def test_19_report_formats_expose_fallback(self):
        with tempfile.TemporaryDirectory() as plain:
            Path(plain, "a.py").write_text("x = 1\n")
            for fmt in ("text", "json", "sarif"):
                with self.subTest(format=fmt):
                    proc = cli(plain, "--check", "secrets.hardcoded_credential", "--format", fmt)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    if fmt == "text":
                        self.assertIn("Git-Ignore NICHT angewendet", proc.stdout)
                    elif fmt == "json":
                        self.assertEqual(json.loads(proc.stdout)["coverage"]["git_ignore_status"], "not_repository")
                    else:
                        run = json.loads(proc.stdout)["runs"][0]
                        self.assertEqual(run["properties"]["coverage"]["git_ignore_status"], "not_repository")
                        self.assertTrue(any(n.get("descriptor", {}).get("id") == "inventory.git_ignore"
                                            for n in run["invocations"][0]["toolExecutionNotifications"]))

    def test_20_declarative_engine_rule_obeys_git_inventory(self):
        self.write(".gitignore", "local/\n")
        self.write("local/api.js", "const u = `/login?password=${pw}`;\n")
        args = (str(self.root), "--strict", "--engine", "required", "--check", "secrets.credential_in_url")
        code, report = cli_json(*args)
        self.assertEqual(code, 0)
        self.assertEqual(report["results"][0]["findings_total"], 0)
        self.write(".gitignore", "")
        code, report = cli_json(*args)
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0]["findings_total"], 1)
        self.git("add", "local/api.js")
        self.write(".gitignore", "local/\n")
        code, report = cli_json(*args)
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0]["findings"][0]["file"], "local/api.js")

    def test_21_ignored_package_resolution_remains_a_finding(self):
        from ruttla.checks.apple.packages import _PBX_WITH_PACKAGE, _RESOLVED_PATH, _RESOLVED
        self.write("App.xcodeproj/project.pbxproj", _PBX_WITH_PACKAGE)
        self.write(_RESOLVED_PATH, _RESOLVED)
        self.write(".gitignore", "*.log\n")
        args = (str(self.root), "--strict", "--check", "apple.package_resolved_not_committed")
        self.assertEqual(cli_json(*args)[0], 0)
        self.write(".gitignore", "*.resolved\n")
        code, report = cli_json(*args)
        self.assertEqual(code, 1)
        self.assertIn("*.resolved", report["results"][0]["findings"][0]["evidence"])

    def test_22_ignored_release_catalog_is_still_validated(self):
        self.write("App.xcodeproj/project.pbxproj", "SDKROOT = iphoneos;\n")
        self.write(".gitignore", "local/\n")
        self.write("local/Strings.xcstrings", '{"version":"1.0","strings":{}}')
        args = (str(self.root), "--strict", "--check", "apple.release.xcstrings_json")
        self.assertEqual(cli_json(*args)[0], 0)
        self.write("local/Strings.xcstrings", "{invalid")
        code, report = cli_json(*args)
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0]["findings"][0]["file"], "local/Strings.xcstrings")


if __name__ == "__main__":
    unittest.main()
