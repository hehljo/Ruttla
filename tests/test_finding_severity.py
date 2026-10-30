"""Finding severity survives the engine unless the profile sets one explicitly.

Before 2026-10-30 the engine overwrote every non-INFO finding with the
check default, so per-finding downgrades (test files) never took effect.
"""
from __future__ import annotations

import base64
import json
import unittest

from _support import cli_json, make_tree

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

    def test_non_public_jwt_in_source_stays_blocking(self):
        source = f"const key = '{SERVICE_JWT}';\n"
        with make_tree({"src/admin.ts": source}) as root:
            code, report = cli_json(root, "--check", CHECK)
        self.assertEqual(findings(report), {"src/admin.ts": ("error", True)})
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
