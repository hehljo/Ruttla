"""Finding severity survives the engine unless the profile sets one explicitly.

Before 2026-10-30 the engine overwrote every non-INFO finding with the
check default, so per-finding downgrades (test files) never took effect.
"""
from __future__ import annotations

import base64
import json
import tempfile
import unittest
from unittest import mock

from _support import cli_json, make_tree

from ruttla.config import Config
from ruttla.context import Context
from ruttla.engine import apply_exit_policy, finding_severity, run_checks
from ruttla.models import CheckResult, Finding, Severity, Status
from ruttla.registry import REGISTRY, Check

CHECK = "secrets.hardcoded_credential"
# Split so the literal in this file is not itself a finding of Ruttla's self-scan.
VALUE = "eUaG2sJ0yF5dB3nH6cW1zK8tR4pX9mL2v7Q"[::-1]
LINE = "export const cfg = { claim_token: '" + VALUE + "' };\n"


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


SERVICE_JWT = ".".join([_b64({"alg": "HS256", "typ": "JWT"}),
                        _b64({"iss": "supabase", "role": "service_role", "ref": "abcdefghij"}),
                        "c2lnbmF0dXJlLXdpdGgtZW5vdWdoLWxlbmd0aA"])


def findings(report: dict) -> dict[str, tuple[str, bool]]:
    return {f["file"]: (f["severity"], f["blocking"])
            for r in report["results"] for f in r["findings"]}


class FindingSeverityTests(unittest.TestCase):
    def test_without_profile_test_files_keep_their_downgrade(self):
        with make_tree({"src/a.ts": LINE, "tests/unit/a.test.ts": LINE}) as root:
            code, report = cli_json(root, "--check", CHECK)
        got = findings(report)
        self.assertEqual(got["src/a.ts"], ("error", True))
        self.assertEqual(got["tests/unit/a.test.ts"], ("warning", False))
        self.assertEqual(code, 1)

    def test_test_file_alone_does_not_block(self):
        with make_tree({"tests/unit/a.test.ts": LINE}) as root:
            code, report = cli_json(root, "--check", CHECK)
        self.assertEqual(findings(report), {"tests/unit/a.test.ts": ("warning", False)})
        self.assertEqual(code, 0)

    def test_explicit_profile_severity_still_overrides(self):
        profile = f'[severity]\n"{CHECK}" = "error"\n'
        with make_tree({".ruttla.toml": profile, "tests/unit/a.test.ts": LINE}) as root:
            code, report = cli_json(root, "--check", CHECK)
        self.assertEqual(findings(report), {"tests/unit/a.test.ts": ("error", True)})
        self.assertEqual(code, 1)

    def test_explicit_profile_downgrade_applies_to_source(self):
        profile = f'[severity]\n"{CHECK}" = "warning"\n'
        with make_tree({".ruttla.toml": profile, "src/a.ts": LINE}) as root:
            _, report = cli_json(root, "--check", CHECK)
        self.assertEqual(findings(report)["src/a.ts"][0], "warning")

    def test_provider_token_in_test_file_stays_blocking(self):
        token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0" + "K1l2M3n4O5p6Q7r8"
        with make_tree({"scripts/deploy.ts": f"const t = '{token}';\n"}) as root:
            code, report = cli_json(root, "--check", CHECK)
        self.assertEqual(findings(report), {"scripts/deploy.ts": ("error", True)})
        self.assertEqual(code, 1)

    def test_non_public_jwt_in_source_stays_blocking(self):
        source = f"const key = '{SERVICE_JWT}';\n"
        with make_tree({"src/admin.ts": source}) as root:
            code, report = cli_json(root, "--check", CHECK)
        self.assertEqual(findings(report), {"src/admin.ts": ("error", True)})
        self.assertEqual(code, 1)


INFO, WARNING, ERROR = Severity.INFO, Severity.WARNING, Severity.ERROR


class SeverityDecisionTests(unittest.TestCase):
    """Die reine Entscheidung, vollständig: jede Befundschwere × jeder Profileintrag."""

    # (Befundschwere, Profileintrag) -> Schwere nach der Engine
    TABLE = {
        (INFO, None): INFO, (WARNING, None): WARNING, (ERROR, None): ERROR,
        (INFO, INFO): INFO, (WARNING, INFO): INFO, (ERROR, INFO): INFO,
        (INFO, WARNING): INFO, (WARNING, WARNING): WARNING, (ERROR, WARNING): WARNING,
        (INFO, ERROR): ERROR, (WARNING, ERROR): ERROR, (ERROR, ERROR): ERROR,
    }

    def test_table_covers_every_combination(self):
        self.assertEqual(len(self.TABLE), len(Severity) * (len(Severity) + 1))

    def test_every_combination(self):
        for (found, override), expected in self.TABLE.items():
            with self.subTest(found=found.value, override=getattr(override, "value", None)):
                self.assertIs(finding_severity(found, override), expected)


class EngineSeverityTests(unittest.TestCase):
    """Der Weg durch ``run_checks``: ein Check, der alle drei Schweren vergibt.

    Der Check-Standard wird je Fall durchgewechselt. Er darf das Ergebnis nie
    verändern: weder nach unten (Herabstufung je Befund) noch nach oben
    (einzelner Befund schwerer als der Standard).
    """

    CHECK_ID = "test.mixed_severity"
    FILES = {"info.txt": INFO, "warning.txt": WARNING, "error.txt": ERROR}

    def run_engine(self, *, default: Severity, overrides: dict[str, str] | None = None,
                   profile: bool = False, safe: bool = False):
        def fn(_ctx):
            return CheckResult(
                check_id=self.CHECK_ID, status=Status.FAIL, title="Mixed",
                findings=[Finding(self.CHECK_ID, sev, "m", file=name)
                          for name, sev in self.FILES.items()],
                units_examined=len(self.FILES))

        check = Check(id=self.CHECK_ID, title="Mixed", platform="universal",
                      default_severity=default, fn=fn, safe_by_default=safe)
        with tempfile.TemporaryDirectory() as root:
            config = Config(severity_overrides=overrides or {},
                            profile_path=f"{root}/.ruttla.toml" if profile or overrides else None)
            with mock.patch.dict(REGISTRY, {self.CHECK_ID: check}, clear=True):
                results = run_checks(Context(root=root, config=config), only_platform=None,
                                     only_checks=[self.CHECK_ID], changed=None)
                code = apply_exit_policy(results, config)
        got = {f.file: (f.severity, f.blocking) for r in results for f in r.findings}
        return code, got

    def test_check_default_never_changes_a_finding(self):
        for default in Severity:
            with self.subTest(default=default.value):
                code, got = self.run_engine(default=default)
                self.assertEqual(got, {"info.txt": (INFO, False), "warning.txt": (WARNING, False),
                                       "error.txt": (ERROR, False)})
                self.assertEqual(code, 0)

    def test_profile_without_entry_keeps_severity_and_blocks_on_error_only(self):
        for default in Severity:
            with self.subTest(default=default.value):
                code, got = self.run_engine(default=default, profile=True)
                self.assertEqual(got, {"info.txt": (INFO, False), "warning.txt": (WARNING, False),
                                       "error.txt": (ERROR, True)})
                self.assertEqual(code, 1)

    def test_safe_by_default_blocks_only_the_error_finding(self):
        code, got = self.run_engine(default=WARNING, safe=True)
        self.assertEqual(got, {"info.txt": (INFO, False), "warning.txt": (WARNING, False),
                               "error.txt": (ERROR, True)})
        self.assertEqual(code, 1)

    def test_profile_entry_overrides_in_both_directions(self):
        cases = {
            "info": ({"info.txt": (INFO, False), "warning.txt": (INFO, False),
                      "error.txt": (INFO, False)}, 0),
            "warning": ({"info.txt": (INFO, False), "warning.txt": (WARNING, False),
                         "error.txt": (WARNING, False)}, 0),
            "error": ({"info.txt": (ERROR, True), "warning.txt": (ERROR, True),
                       "error.txt": (ERROR, True)}, 1),
        }
        for value, (expected, expected_code) in cases.items():
            for pattern in (self.CHECK_ID, "test.*"):
                with self.subTest(value=value, pattern=pattern):
                    code, got = self.run_engine(default=WARNING, overrides={pattern: value})
                    self.assertEqual(got, expected)
                    self.assertEqual(code, expected_code)

    def test_entry_for_another_check_is_no_override(self):
        code, got = self.run_engine(default=ERROR, overrides={"other.*": "info"})
        self.assertEqual(got["warning.txt"], (WARNING, False))
        self.assertEqual(got["error.txt"], (ERROR, True))
        self.assertEqual(code, 1)

    def test_off_removes_the_check_instead_of_changing_severity(self):
        code, got = self.run_engine(default=ERROR, overrides={self.CHECK_ID: "off"})
        self.assertEqual(got, {})


if __name__ == "__main__":
    unittest.main()
