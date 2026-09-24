"""Public contracts (P01): exit codes, blocking model, report schema, agent
format, profile names, platform registry, coverage diagnostics, trust boundary."""

from __future__ import annotations

import json
import random
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO, cli, cli_json, ensure_checks_loaded, make_tree

from ruttla.config import Config
from ruttla.engine import (
    EXIT_CRASH, EXIT_FAILED, EXIT_OK, EXIT_UNMEASURED, apply_exit_policy,
)
from ruttla.models import CheckResult, ConfigError, Finding, Severity, Status
from ruttla.registry import REGISTRY, Check

TOKEN = "ghp_" + "a" * 36
HARD_FILE = {"a.ts": f'const token = "{TOKEN}";\n'}
SOFT_FILE = {"gate.ts": 'const pos = src.indexOf("Storyboard generieren");\n'}

try:  # optional dev dependency
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


def legacy_exit(results: list[CheckResult], config: Config, safe_ids: set[str]) -> int:
    """The pre-0.1 runner logic, verbatim, as the equivalence oracle."""
    if any(r.status == Status.ERROR for r in results):
        code = EXIT_CRASH
    elif any(f.severity == Severity.ERROR for r in results if r.status == Status.FAIL
             for f in r.findings):
        code = EXIT_FAILED
    elif not [r for r in results if r.status in (Status.PASS, Status.FAIL)]:
        code = EXIT_UNMEASURED
    else:
        code = EXIT_OK
    if code == EXIT_OK and config.strict and any(r.status == Status.FAIL for r in results):
        code = EXIT_FAILED
    if code == EXIT_FAILED and not config.profile_path and not config.strict:
        hard = any(f.severity == Severity.ERROR for r in results if r.check_id in safe_ids
                   for f in r.findings)
        if not hard:
            code = EXIT_OK
    return code


class ExitCodeContractTests(unittest.TestCase):
    def test_exit_zero_measured_without_blocking(self) -> None:
        with make_tree(SOFT_FILE) as tmp:
            code, report = cli_json(tmp, "--check", "quality.display_text_as_anchor")
        self.assertEqual(code, 0)
        self.assertEqual(report["verdict"], "green")
        self.assertEqual(report["blocking_findings"], 0)
        self.assertEqual(report["advisory_findings"], 1)
        self.assertFalse(report["results"][0]["findings"][0]["blocking"])

    def test_exit_one_for_blocking_finding(self) -> None:
        with make_tree(HARD_FILE) as tmp:
            code, report = cli_json(tmp, "--check", "secrets.hardcoded_credential")
        self.assertEqual(code, 1)
        self.assertEqual(report["blocking_findings"], 1)
        self.assertTrue(report["results"][0]["findings"][0]["blocking"])

    def test_exit_two_when_nothing_measured(self) -> None:
        with make_tree({"notes.txt": "hello\n"}) as tmp:
            code, report = cli_json(tmp, "--check", "secrets.hardcoded_credential")
        self.assertEqual(code, 2)
        self.assertEqual(report["verdict"], "unmeasured")

    def test_exit_three_for_invalid_input(self) -> None:
        proc = cli("/definitely/not/a/dir", "--format", "json")
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(json.loads(proc.stdout)["runner_state"]["id"], "invalid_root")

    def test_policy_is_equivalent_to_legacy_logic(self) -> None:
        rng = random.Random(20260924)
        for _ in range(3000):
            n = rng.randint(1, 5)
            checks, results = {}, []
            for i in range(n):
                cid = f"test.c{i}"
                checks[cid] = Check(cid, cid, "universal", Severity.WARNING,
                                    lambda _c: None, safe_by_default=rng.random() < 0.4)
                status = rng.choice(list(Status))
                findings = []
                if status == Status.FAIL:
                    findings = [Finding(cid, rng.choice(list(Severity)), "m")
                                for _ in range(rng.randint(1, 3))]
                results.append(CheckResult(cid, status, cid, findings=findings,
                                           units_examined=1, reason="r"))
            config = Config(strict=rng.random() < 0.3,
                            profile_path="/p/.ruttla.toml" if rng.random() < 0.4 else None)
            safe = {cid for cid, c in checks.items() if c.safe_by_default}
            with mock.patch.dict(REGISTRY, checks, clear=True):
                new = apply_exit_policy(results, config)
            self.assertEqual(new, legacy_exit(results, config, safe))
            blocking = any(f.blocking for r in results for f in r.findings)
            if new == EXIT_FAILED:
                self.assertTrue(blocking)
            if new == EXIT_OK:
                self.assertFalse(blocking)


class ReportFormatTests(unittest.TestCase):
    def test_json_report_validates_against_published_schema(self) -> None:
        if jsonschema is None:
            self.skipTest("jsonschema not installed")
        schema = json.loads((REPO / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        fixtures = REPO / "tests" / "fixtures" / "packs"
        trees = [fixtures / "apple" / "broken", fixtures / "universal" / "broken",
                 fixtures / "web" / "healthy"]
        for tree in trees:
            with self.subTest(tree=tree.name):
                _, report = cli_json(str(tree), "--max-findings", "1000")
                errors = sorted(validator.iter_errors(report), key=str)
                self.assertEqual([e.message for e in errors[:3]], [])
        proc = cli("/definitely/not/a/dir", "--format", "json")
        self.assertEqual(list(validator.iter_errors(json.loads(proc.stdout))), [])

    def test_agent_format_only_appends_fields(self) -> None:
        with make_tree({**HARD_FILE, **SOFT_FILE}) as tmp:
            proc = cli(tmp, "--check", "secrets.*", "--check", "quality.*", "--format", "agent")
        header, *rest = proc.stdout.splitlines()
        self.assertTrue(header.startswith("VERDICT=failed EXIT=1 PASS="))
        for key in ("SCHEMA=1.1", "BLOCKING=1", "ADVISORY=", "SKIPPED=0"):
            self.assertIn(key, header)
        finding = next(line for line in rest if line.startswith("ERROR\t"))
        fields = finding.split("\t")
        self.assertEqual(fields[1], "secrets.hardcoded_credential")
        self.assertTrue(fields[4].startswith("FIX: "))
        self.assertEqual(fields[5], "BLOCKING=true")
        self.assertTrue(rest[-1].startswith("NEXT_ACTION\t"))

    def test_version_flag(self) -> None:
        proc = cli("--version")
        self.assertEqual(proc.returncode, 0)
        self.assertRegex(proc.stdout, r"^ruttla \d+\.\d+\.\d+\S* \(report schema 1\.\d+\)")


class ProfileTests(unittest.TestCase):
    def load(self, files: dict[str, str]) -> Config:
        with make_tree(files) as tmp:
            return Config.load(tmp)

    def test_new_profile_name_is_read(self) -> None:
        cfg = self.load({".ruttla.toml": "[gate]\nstrict = true\n"})
        self.assertTrue(cfg.strict)
        self.assertTrue(cfg.profile_path.endswith(".ruttla.toml"))

    def test_legacy_profile_name_is_still_read(self) -> None:
        cfg = self.load({".qualitygate.toml": "[gate]\nstrict = true\n"})
        self.assertTrue(cfg.strict)

    def test_two_profiles_are_ambiguous(self) -> None:
        with self.assertRaises(ConfigError):
            self.load({".ruttla.toml": "", ".qualitygate.toml": ""})

    def test_config_version(self) -> None:
        self.assertEqual(self.load({".ruttla.toml": "config_version = 1\n"}).config_version, 1)
        for bad in ("config_version = 2\n", "config_version = true\n", 'config_version = "1"\n'):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                self.load({".ruttla.toml": bad})


class PlatformRegistryTests(unittest.TestCase):
    def test_project_platform_forces_pack_additively(self) -> None:
        # A shell-only tree is not detected as godot; the profile forces it on.
        with make_tree({"run.sh": "echo hi\n",
                        ".ruttla.toml": '[project]\nplatform = "godot"\n'}) as tmp:
            _, report = cli_json(tmp)
        self.assertIn("godot", report["platforms_detected"])
        self.assertIn("universal", report["platforms_detected"])
        self.assertTrue(any(r["platform"] == "godot" for r in report["results"]))

    def test_platform_without_pack_is_rejected_in_profile(self) -> None:
        with make_tree({".ruttla.toml": '[project]\nplatform = "dotnet"\n'}) as tmp:
            with self.assertRaisesRegex(ConfigError, "kein Regelpaket"):
                Config.load(tmp)

    def test_platform_without_pack_is_rejected_on_cli(self) -> None:
        with make_tree({"a.py": "x = 1\n"}) as tmp:
            proc = cli(tmp, "--platform", "dotnet", "--format", "agent")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("ohne Regelpaket", proc.stdout)

    def test_detected_platform_without_pack_is_reported(self) -> None:
        with make_tree({"App.cs": "class A {}\n", "a.py": "x = 1\n"}) as tmp:
            _, report = cli_json(tmp)
        self.assertIn("dotnet", report["platforms_without_pack"])


class CoverageDiagnosticsTests(unittest.TestCase):
    def test_oversize_file_is_reported_not_silently_skipped(self) -> None:
        big = "x = 1\n" * 50
        with make_tree({"big.py": big, "small.py": "y = 2\n",
                        ".ruttla.toml": "[gate]\nmax_file_bytes = 100\n"}) as tmp:
            code, report = cli_json(tmp)
            agent = cli(tmp, "--format", "agent").stdout
        skipped = report["coverage"]["files_skipped"]
        self.assertEqual(skipped, [{"file": "big.py", "reason": "max_file_bytes",
                                    "bytes": len(big)}])
        self.assertIn("max_file_bytes", report["next_action"])
        self.assertIn("SKIPPED\tbig.py\tmax_file_bytes", agent)
        self.assertIn(code, (0, 1, 2))

    def test_exclude_glob_applies_to_project_directories(self) -> None:
        # Regression (dogfood scan 2026-09-24): an .xcodeproj under an
        # excluded glob switched the apple pack on and was reported.
        pbx = (REPO / "tests/fixtures/packs/apple/broken/apple.api_availability_unguarded/"
               "P.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
        files = {"vendor2/App.xcodeproj/project.pbxproj": pbx, "a.py": "x = 1\n"}
        with make_tree(files) as tmp:
            _, unexcluded = cli_json(tmp)
        with make_tree({**files, ".ruttla.toml": '[gate]\nexclude = ["vendor2/**"]\n'}) as tmp:
            _, excluded = cli_json(tmp)
        settings = [r for r in unexcluded["results"] if r["check_id"] == "apple.project_settings"]
        self.assertIn("apple", unexcluded["platforms_detected"])
        self.assertEqual(settings[0]["status"], "fail")
        self.assertNotIn("apple", excluded["platforms_detected"])
        self.assertFalse(any(f["file"] and f["file"].startswith("vendor2/")
                             for r in excluded["results"] for f in r["findings"]))

    def test_pack_level_walk_reports_its_size_skips(self) -> None:
        # .xcassets content is walked by the apple release pack itself; its
        # size skips must be as visible as the main inventory's.
        big = '{"images": [], "info": {"version": 1, "author": "xcode"}}' + " " * 400
        with make_tree({"App/Assets.xcassets/AppIcon.appiconset/Contents.json": big,
                        "App/Assets.xcassets/Small.imageset/Contents.json": '{"info": {}}',
                        ".ruttla.toml": "[gate]\nmax_file_bytes = 200\n"}) as tmp:
            _, report = cli_json(tmp, "--check", "apple.release.asset_contents_json")
        skipped = [s["file"] for s in report["coverage"]["files_skipped"]]
        self.assertIn("App/Assets.xcassets/AppIcon.appiconset/Contents.json", skipped)
        self.assertEqual(report["coverage"]["files_skipped_total"], len(skipped))

    def test_readme_is_measured_but_agent_files_are_not(self) -> None:
        snippet = "```bash\n./app --join=<HOST_IP>\n```\n"
        with make_tree({"README.md": snippet, "CLAUDE.md": snippet}) as tmp:
            code, report = cli_json(tmp, "--check", "docs.unquoted_shell_placeholder")
        result = report["results"][0]
        self.assertEqual(result["status"], "fail")
        self.assertEqual({f["file"] for f in result["findings"]}, {"README.md"})
        self.assertEqual(report["coverage"]["files_excluded_agent_instructions"], 1)
        self.assertEqual(code, 0)  # error-level, but not safe_by_default: advisory without profile
        self.assertFalse(result["findings"][0]["blocking"])

    def test_rule_docs_marker_excludes_generated_rule_docs(self) -> None:
        body = "<!-- ruttla:rule-docs -->\n```bash\n./app --join=<HOST_IP>\n```\n"
        with make_tree({"docs/RULES.md": body, "README.md": "# ok\n"}) as tmp:
            _, report = cli_json(tmp, "--check", "docs.unquoted_shell_placeholder")
        self.assertEqual(report["results"][0]["status"], "pass")


class TrustBoundaryTests(unittest.TestCase):
    def test_python_in_scan_target_is_never_executed(self) -> None:
        marker = "executed.marker"
        evil = (
            "from ruttla.core import register\n"
            "import pathlib\n"
            f"pathlib.Path(__file__).with_name('{marker}').write_text('x')\n"
            "@register('evil.check', 'Evil')\n"
            "def evil(ctx):\n    return None\n"
        )
        with make_tree({"checks/evil.py": evil, "ruttla/checks/x.py": evil}) as tmp:
            code, report = cli_json(tmp)
            self.assertFalse(Path(tmp, "checks", marker).exists())
            self.assertFalse(Path(tmp, "ruttla", "checks", marker).exists())
        self.assertNotIn("evil.check", {r["check_id"] for r in report["results"]})
        ensure_checks_loaded()
        self.assertNotIn("evil.check", REGISTRY)


if __name__ == "__main__":
    unittest.main()
