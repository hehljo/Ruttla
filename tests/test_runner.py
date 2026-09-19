from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import core
import master_gate
from core import (
    REGISTRY,
    ChangedFilesError,
    Check,
    CheckResult,
    Config,
    ConfigError,
    Context,
    Finding,
    GateInputError,
    SelfTestCase,
    Severity,
    Status,
)


class ConfigTests(unittest.TestCase):
    def load_text(self, text: str) -> Config:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".qualitygate.toml").write_text(text, encoding="utf-8")
            return Config.load(tmp)

    def test_valid_config_types_are_preserved(self) -> None:
        cfg = self.load_text(textwrap.dedent("""
            [gate]
            strict = true
            exclude = ["legacy/**"]
            exclude_dirs = ["generated"]
            max_file_bytes = 1234
            [brand]
            names = ["Example"]
            sources = ["src/brand.py"]
            [severity]
            "quality.*" = "warning"
        """))
        self.assertTrue(cfg.strict)
        self.assertEqual(cfg.exclude_globs, ["legacy/**"])
        self.assertEqual(cfg.exclude_dirs, ["generated"])
        self.assertEqual(cfg.max_file_bytes, 1234)
        self.assertEqual(cfg.severity_overrides, {"quality.*": "warning"})

    def test_invalid_toml_is_not_silently_ignored(self) -> None:
        with self.assertRaises(ConfigError):
            self.load_text("[gate\nstrict=true\n")

    def test_explicit_missing_config_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                Config.load(tmp, str(Path(tmp, "missing.toml")))

    def test_string_is_not_accepted_as_boolean(self) -> None:
        with self.assertRaises(ConfigError):
            self.load_text('[gate]\nstrict = "false"\n')

    def test_string_is_not_split_into_exclude_list(self) -> None:
        with self.assertRaises(ConfigError):
            self.load_text('[gate]\nexclude = "legacy/**"\n')

    def test_boolean_is_not_accepted_as_file_size(self) -> None:
        with self.assertRaises(ConfigError):
            self.load_text("[gate]\nmax_file_bytes = true\n")

    def test_invalid_severity_is_rejected_during_load(self) -> None:
        with self.assertRaises(ConfigError):
            self.load_text('[severity]\n"quality.*" = "fatal"\n')

    def test_project_metadata_and_singular_brand_source_are_supported(self) -> None:
        cfg = self.load_text(textwrap.dedent("""
            [project]
            name = "Henga"
            platform = "apple"
            [brand]
            source = "Sources/Core/AppConfig.swift:brandName"
        """))
        self.assertEqual(cfg.brand_names, ["Henga"])
        self.assertEqual(cfg.brand_source_globs, ["Sources/Core/AppConfig.swift"])

    def test_unknown_table_is_rejected_during_load(self) -> None:
        with self.assertRaises(ConfigError):
            self.load_text("[gtae]\nstrict = true\n")

    def test_unknown_gate_key_is_rejected_during_load(self) -> None:
        with self.assertRaises(ConfigError):
            self.load_text("[gate]\nstrcit = true\n")


class InputAndGitTests(unittest.TestCase):
    def git(self, cwd: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_dangling_input_is_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "broken.py").symlink_to(Path(tmp, "missing.py"))
            with self.assertRaises(GateInputError):
                Context(tmp, Config()).all_files()

    def test_readable_symlink_cannot_escape_input_root(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent, "root")
            root.mkdir()
            outside = Path(parent, "outside.py")
            outside.write_text("secret = 1\n", encoding="utf-8")
            Path(root, "linked.py").symlink_to(outside)
            with self.assertRaises(GateInputError):
                Context(str(root), Config()).all_files()

    def test_changed_files_are_relative_to_subdirectory_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp, "repo")
            sub = repo / "sub"
            sub.mkdir(parents=True)
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "test@example.invalid")
            self.git(repo, "config", "user.name", "Test")
            (repo / "root.py").write_text("root\n", encoding="utf-8")
            (sub / "inside.py").write_text("inside\n", encoding="utf-8")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-qm", "initial")
            (repo / "root.py").write_text("changed root\n", encoding="utf-8")
            (sub / "inside.py").write_text("changed inside\n", encoding="utf-8")

            changed = Context(str(sub), Config()).changed_files("HEAD")
            self.assertEqual(changed, ["inside.py"])

    def test_changed_files_include_untracked_files_in_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp, "repo")
            sub = repo / "sub"
            sub.mkdir(parents=True)
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "test@example.invalid")
            self.git(repo, "config", "user.name", "Test")
            (repo / "tracked.py").write_text("tracked\n", encoding="utf-8")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-qm", "initial")
            (repo / "outside.py").write_text("outside\n", encoding="utf-8")
            (sub / "new.py").write_text("new\n", encoding="utf-8")

            changed = Context(str(sub), Config()).changed_files("HEAD")
            self.assertEqual(changed, ["new.py"])

    def test_invalid_git_reference_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.git(repo, "init", "-q")
            with self.assertRaises(ChangedFilesError):
                Context(tmp, Config()).changed_files("missing-ref")

    def test_git_path_escape_is_rejected(self) -> None:
        top = subprocess.CompletedProcess([], 0, stdout="/repo\n", stderr="")
        diff = subprocess.CompletedProcess([], 0, stdout=b"../escape.py\0", stderr=b"")
        untracked = subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")
        with mock.patch.object(core.subprocess, "run", side_effect=[top, diff, untracked]):
            with self.assertRaises(ChangedFilesError):
                Context("/repo/sub", Config()).changed_files("HEAD")


class ReportTests(unittest.TestCase):
    def make_report(self, max_findings: int) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.py").write_text("x = 1\n", encoding="utf-8")
            findings = [
                Finding("test.findings", Severity.ERROR, "first", "a.py", 1),
                Finding("test.findings", Severity.WARNING, "second", "a.py", 1),
                Finding("test.findings", Severity.INFO, "third", "a.py", 1),
            ]
            result = CheckResult(
                "test.findings", Status.FAIL, "Findings", findings=findings,
                units_examined=1,
            )
            ctx = Context(tmp, Config())
            return master_gate.build_report(
                ctx, [result], master_gate.EXIT_FAILED, max_findings,
            )

    def test_truncation_reports_total_emitted_and_omitted_counts(self) -> None:
        report = self.make_report(2)
        result = report["results"][0]
        self.assertEqual(result["findings_total"], 3)
        self.assertEqual(result["findings_emitted"], 2)
        self.assertEqual(result["findings_truncated"], 1)
        self.assertEqual(report["findings_truncated"], 1)
        self.assertEqual(report["findings_by_severity"], {
            "error": 1, "warning": 1, "info": 1,
        })
        self.assertEqual(report["findings_emitted_by_severity"], {
            "error": 1, "warning": 1, "info": 0,
        })

    def test_zero_limit_reports_all_findings_as_truncated(self) -> None:
        report = self.make_report(0)
        result = report["results"][0]
        self.assertEqual(result["findings_emitted"], 0)
        self.assertEqual(result["findings_truncated"], 3)
        self.assertEqual(result["findings"], [])

    def test_agent_output_keeps_finding_on_one_line(self) -> None:
        report = self.make_report(3)
        report["results"][0]["findings"][0]["message"] = "line one\nline\ttwo"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            master_gate.print_agent(report)
        finding_lines = [line for line in output.getvalue().splitlines() if line.startswith("ERROR\t")]
        self.assertEqual(len(finding_lines), 1)
        self.assertIn("line one line two", finding_lines[0])


class PluginAndResultTests(unittest.TestCase):
    def make_check(self, fn, check_id: str = "test.plugin") -> Check:
        return Check(
            id=check_id,
            title="Plugin",
            platform="universal",
            default_severity=Severity.ERROR,
            fn=fn,
        )

    def test_empty_plugin_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "empty.py").write_text("VALUE = 1\n", encoding="utf-8")
            with mock.patch.dict(REGISTRY, {}, clear=True):
                with self.assertRaises(master_gate.PluginLoadError):
                    master_gate.load_checks(tmp)

    def test_plugin_import_failure_is_identified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "broken.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
            with mock.patch.dict(REGISTRY, {}, clear=True):
                with self.assertRaisesRegex(master_gate.PluginLoadError, "broken.py"):
                    master_gate.load_checks(tmp)

    def test_partial_plugin_registration_is_rolled_back_on_failure(self) -> None:
        source = textwrap.dedent("""
            from core import register
            @register("test.partial", "Partial")
            def partial(_ctx):
                return None
            raise RuntimeError("boom")
        """)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "partial.py").write_text(source, encoding="utf-8")
            with mock.patch.dict(REGISTRY, {}, clear=True):
                with self.assertRaises(master_gate.PluginLoadError):
                    master_gate.load_checks(tmp)
                self.assertNotIn("test.partial", REGISTRY)

    def test_non_result_from_plugin_becomes_runner_error(self) -> None:
        check = self.make_check(lambda _ctx: None)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            REGISTRY, {check.id: check}, clear=True
        ):
            results = master_gate.run_checks(
                Context(tmp, Config()), only_platform=None, only_checks=[], changed=None,
            )
        self.assertEqual(results[0].status, Status.ERROR)
        self.assertEqual(master_gate.worst_exit(results), master_gate.EXIT_CRASH)

    def test_false_pass_with_zero_units_becomes_runner_error(self) -> None:
        check = self.make_check(
            lambda _ctx: CheckResult("test.plugin", Status.PASS, "Plugin")
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            REGISTRY, {check.id: check}, clear=True
        ):
            results = master_gate.run_checks(
                Context(tmp, Config()), only_platform=None, only_checks=[], changed=None,
            )
        self.assertEqual(results[0].status, Status.ERROR)
        self.assertIn("null geprüften Einheiten", results[0].reason or "")


class SelfTestCompletenessTests(unittest.TestCase):
    def run_isolated(self, checks: dict[str, Check]) -> tuple[int, str]:
        output = io.StringIO()
        with mock.patch.dict(REGISTRY, checks, clear=True), contextlib.redirect_stdout(output):
            code = master_gate.run_self_test(use_color=False)
        return code, output.getvalue()

    def test_zero_registered_checks_is_unmeasured(self) -> None:
        code, output = self.run_isolated({})
        self.assertEqual(code, master_gate.EXIT_UNMEASURED)
        self.assertIn("null Sabotage-Proben", output)

    def test_check_without_self_tests_fails(self) -> None:
        check = Check(
            "test.none", "None", "universal", Severity.WARNING,
            lambda _ctx: CheckResult("test.none", Status.PASS, "None", units_examined=1),
        )
        code, output = self.run_isolated({check.id: check})
        self.assertEqual(code, master_gate.EXIT_FAILED)
        self.assertIn("keine Sabotage-Probe", output)

    def test_fail_and_unmeasured_do_not_replace_healthy_coverage(self) -> None:
        def fn(ctx: Context) -> CheckResult:
            if ctx.files_named("bad.txt"):
                return CheckResult(
                    "test.directions", Status.FAIL, "Directions",
                    findings=[Finding("test.directions", Severity.WARNING, "bad")],
                    units_examined=1,
                )
            return CheckResult(
                "test.directions", Status.UNMEASURED, "Directions", reason="none",
            )

        check = Check(
            "test.directions", "Directions", "universal", Severity.WARNING, fn,
            self_tests=[
                SelfTestCase("negative", {"bad.txt": "bad"}, Status.FAIL),
                SelfTestCase("not healthy", {}, Status.UNMEASURED),
            ],
        )
        code, output = self.run_isolated({check.id: check})
        self.assertEqual(code, master_gate.EXIT_FAILED)
        self.assertIn("healthy=pass", output)

    def test_probe_exception_is_failure_not_process_crash(self) -> None:
        def fn(_ctx: Context) -> CheckResult:
            raise RuntimeError("boom")

        check = Check(
            "test.crash", "Crash", "universal", Severity.WARNING, fn,
            self_tests=[
                SelfTestCase("negative", {"bad.txt": "bad"}, Status.FAIL),
                SelfTestCase("healthy", {"good.txt": "good"}, Status.PASS),
            ],
        )
        code, output = self.run_isolated({check.id: check})
        self.assertEqual(code, master_gate.EXIT_FAILED)
        self.assertIn("Probe abgestürzt", output)


class CliContractTests(unittest.TestCase):
    def run_cli(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(REPO / "master_gate.py"), *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=60,
        )

    def test_list_is_exit_zero(self) -> None:
        result = self.run_cli("--list", "--no-color")
        self.assertEqual(result.returncode, master_gate.EXIT_OK, result.stderr)

    def test_argparse_error_uses_exit_three(self) -> None:
        result = self.run_cli(".", "--max-findings", "nope", "--no-color")
        self.assertEqual(result.returncode, master_gate.EXIT_CRASH)
        self.assertIn("RUNNER_ERROR\tinvalid_arguments", result.stderr)

    def test_negative_limit_uses_exit_three(self) -> None:
        result = self.run_cli(".", "--max-findings", "-1", "--format", "agent")
        self.assertEqual(result.returncode, master_gate.EXIT_CRASH)
        self.assertIn("RUNNER_ERROR\tinvalid_arguments", result.stdout)

    def test_unknown_check_uses_exit_three(self) -> None:
        result = self.run_cli(".", "--check", "does.not.exist", "--format", "agent")
        self.assertEqual(result.returncode, master_gate.EXIT_CRASH)
        self.assertIn("RUNNER_ERROR\tunknown_check", result.stdout)

    def test_unknown_platform_uses_exit_three(self) -> None:
        result = self.run_cli(".", "--platform", "does-not-exist", "--format", "agent")
        self.assertEqual(result.returncode, master_gate.EXIT_CRASH)
        self.assertIn("RUNNER_ERROR\tunknown_platform", result.stdout)

    def test_invalid_config_uses_exit_three(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".qualitygate.toml").write_text("[gate\n", encoding="utf-8")
            Path(tmp, "a.py").write_text("x = 1\n", encoding="utf-8")
            result = self.run_cli(tmp, "--format", "agent")
        self.assertEqual(result.returncode, master_gate.EXIT_CRASH)
        self.assertIn("RUNNER_ERROR\tinvalid_config", result.stdout)

    def test_unreadable_input_uses_exit_three(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "broken.py").symlink_to(Path(tmp, "missing.py"))
            result = self.run_cli(tmp, "--format", "agent")
        self.assertEqual(result.returncode, master_gate.EXIT_CRASH)
        self.assertIn("RUNNER_ERROR\tinput_unreadable", result.stdout)

    def test_no_enabled_checks_is_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.py").write_text("x = 1\n", encoding="utf-8")
            Path(tmp, ".qualitygate.toml").write_text(
                '[severity]\n"*" = "off"\n', encoding="utf-8"
            )
            result = self.run_cli(tmp, "--format", "agent")
        self.assertEqual(result.returncode, master_gate.EXIT_UNMEASURED)
        self.assertIn("RUNNER_UNMEASURED\tzero_checks_run", result.stdout)

    def test_changed_only_with_no_changes_is_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.name", "Test"], check=True)
            (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", tmp, "add", "."], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "initial"], check=True)
            result = self.run_cli(tmp, "--changed-only", "HEAD", "--format", "agent")
        self.assertEqual(result.returncode, master_gate.EXIT_UNMEASURED)
        self.assertIn("RUNNER_UNMEASURED\tchanged_only_empty", result.stdout)

    def test_invalid_changed_only_reference_is_exit_three(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
            result = self.run_cli(tmp, "--changed-only", "missing", "--format", "agent")
        self.assertEqual(result.returncode, master_gate.EXIT_CRASH)
        self.assertIn("RUNNER_ERROR\tchanged_only_failed", result.stdout)

    def test_soft_warning_remains_exit_zero_without_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "gate.ts").write_text(
                'const pos = src.indexOf("Storyboard generieren");\n', encoding="utf-8"
            )
            result = self.run_cli(
                tmp, "--check", "quality.display_text_as_anchor", "--format", "agent"
            )
        self.assertEqual(result.returncode, master_gate.EXIT_OK, result.stdout + result.stderr)
        self.assertIn("FAIL=1", result.stdout)
        self.assertIn("WARNINGS=1", result.stdout)

    def test_strict_promotes_soft_failure_to_exit_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "gate.ts").write_text(
                'const pos = src.indexOf("Storyboard generieren");\n', encoding="utf-8"
            )
            result = self.run_cli(
                tmp, "--check", "quality.display_text_as_anchor", "--strict",
                "--format", "agent",
            )
        self.assertEqual(result.returncode, master_gate.EXIT_FAILED, result.stdout + result.stderr)
        self.assertIn("VERDICT=failed EXIT=1", result.stdout)

    def test_hard_finding_is_exit_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token = "ghp_" + "a" * 36
            Path(tmp, "a.ts").write_text(f'const token = "{token}";\n', encoding="utf-8")
            result = self.run_cli(
                tmp, "--check", "secrets.hardcoded_credential", "--format", "agent"
            )
        self.assertEqual(result.returncode, master_gate.EXIT_FAILED, result.stdout + result.stderr)
        self.assertIn("VERDICT=failed EXIT=1", result.stdout)


if __name__ == "__main__":
    unittest.main()
