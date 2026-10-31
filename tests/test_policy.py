"""Ausnahmen (baseline), Policy aus vertrauter Referenz (--trusted-ref) und Umgehungswächter."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import subprocess
import unittest
from pathlib import Path

import _support  # noqa: F401  (Importpfad, eigenes Statistikverzeichnis)
from _support import make_tree

from ruttla import baseline, cli, guard

CHECK = "secrets.hardcoded_credential"
SECRET = hashlib.sha256(b"ruttla-policy").hexdigest()[:36]
LINE = "  claim_" + "token: '" + SECRET + "',\n"
TODAY = dt.date.today()


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tree({"src/a.ts": "const cfg = {\n" + LINE + "};\n",
                              "tests/test_a.py": "def test_one():\n    pass\n\n"
                                                 "def test_two():\n    pass\n"})
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "t"]):
            self.git(*args)
        self.commit("start")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", self.root, *args], check=True,
                              capture_output=True, text=True).stdout

    def commit(self, msg: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)

    def write(self, rel: str, text: str) -> None:
        path = Path(self.root, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def scan(self, *extra: str) -> tuple[int, dict]:
        code, out, _ = run(self.root, "--format", "json", "--check", CHECK, "--strict", *extra)
        return code, json.loads(out)


class BaselineTests(RepoCase):
    def test_no_baseline_leaves_report_unchanged(self) -> None:
        code, report = self.scan()
        self.assertEqual(code, 1)
        self.assertNotIn("baseline", report)

    def test_create_accepts_legacy_and_unblocks(self) -> None:
        code, _, err = run("baseline", "create", self.root, "--reason", "Altlast",
                           "--expires", (TODAY + dt.timedelta(days=30)).isoformat())
        self.assertEqual(code, 0, err)
        code, report = self.scan()
        self.assertEqual(code, 0)
        self.assertEqual(report["baseline"]["suppressed"], 1)
        # Ohne verbleibenden Befund ist der Check bestanden, nicht „fail mit 0 Befunden“.
        status = {r["check_id"]: r["status"] for r in report["results"]}
        self.assertEqual(status[CHECK], "pass")

    def test_create_refuses_second_time(self) -> None:
        exp = (TODAY + dt.timedelta(days=30)).isoformat()
        run("baseline", "create", self.root, "--reason", "Altlast", "--expires", exp)
        # Ein neuer Befund darf nicht per zweitem create still mit hinein.
        self.write("src/b.ts", "const b = {\n" + LINE + "};\n")
        self.assertEqual(run("baseline", "create", self.root, "--reason", "x",
                             "--expires", exp)[0], 1)
        self.assertEqual(self.scan()[0], 1)

    def test_second_identical_finding_still_blocks(self) -> None:
        run("baseline", "create", self.root, "--reason", "Altlast",
            "--expires", (TODAY + dt.timedelta(days=30)).isoformat())
        self.write("src/a.ts", "const cfg = {\n" + LINE + "};\nconst b = {\n" + LINE + "};\n")
        code, report = self.scan()
        self.assertEqual(code, 1)
        self.assertEqual(report["baseline"]["suppressed"], 1)

    def test_expired_entry_blocks_again(self) -> None:
        run("baseline", "create", self.root, "--reason", "Altlast",
            "--expires", (TODAY + dt.timedelta(days=30)).isoformat())
        path = Path(self.root, baseline.BASELINE_PATH)
        entries = baseline.parse(path.read_text(encoding="utf-8"))
        for e in entries:
            e.added, e.expires = TODAY - dt.timedelta(days=10), TODAY - dt.timedelta(days=1)
        path.write_text(baseline.render(entries), encoding="utf-8")
        code, report = self.scan()
        self.assertEqual((code, report["baseline"]["suppressed"]), (1, 0))
        self.assertEqual(len(report["baseline"]["expired"]), 1)

    def test_stale_entry_is_reported(self) -> None:
        run("baseline", "create", self.root, "--reason", "Altlast",
            "--expires", (TODAY + dt.timedelta(days=30)).isoformat())
        self.write("src/a.ts", "const cfg = {};\n")
        code, report = self.scan()
        self.assertEqual((code, len(report["baseline"]["stale"])), (0, 1))

    def test_invalid_baseline_is_exit_3(self) -> None:
        for text in ('schema = "ruttla-baseline/1"\n[[accepted]]\nfingerprint = "x"\n',
                     baseline.render([baseline.Entry("f", CHECK, "a", 1, " ", TODAY, TODAY)]),
                     baseline.render([baseline.Entry("f", CHECK, "a", 1, "r",
                                                     TODAY + dt.timedelta(days=400), TODAY)])):
            self.write(baseline.BASELINE_PATH, text)
            self.assertEqual(run(self.root, "--check", CHECK)[0], 3)

    def test_expires_beyond_a_year_is_refused(self) -> None:
        self.assertEqual(run("baseline", "create", self.root, "--reason", "x", "--expires",
                             (TODAY + dt.timedelta(days=400)).isoformat())[0], 1)


class TrustedRefTests(RepoCase):
    def test_local_baseline_does_not_count_against_trusted_ref(self) -> None:
        run("baseline", "create", self.root, "--reason", "Agent",
            "--expires", (TODAY + dt.timedelta(days=30)).isoformat())
        self.assertEqual(self.scan()[0], 0)  # lokal wirkt sie …
        self.assertEqual(self.scan("--trusted-ref", "main")[0], 1)  # … gegen main nicht

    def test_committed_baseline_counts(self) -> None:
        run("baseline", "create", self.root, "--reason", "Altlast",
            "--expires", (TODAY + dt.timedelta(days=30)).isoformat())
        self.commit("baseline")
        self.assertEqual(self.scan("--trusted-ref", "main")[0], 0)

    def test_local_profile_cannot_switch_rule_off(self) -> None:
        self.write(".ruttla.toml", f'[severity]\n"{CHECK}" = "off"\n')
        code, _, _ = run(self.root, "--format", "json", "--check", CHECK)
        self.assertNotEqual(code, 1)  # lokal abgeschaltet: nichts blockiert
        code, out, _ = run(self.root, "--format", "json", "--check", CHECK,
                           "--trusted-ref", "main")
        self.assertEqual((code, json.loads(out)["blocking_findings"]), (1, 1))

    def test_unknown_ref_and_config_conflict_are_exit_3(self) -> None:
        self.assertEqual(run(self.root, "--trusted-ref", "nope", "--check", CHECK)[0], 3)
        self.assertEqual(run(self.root, "--trusted-ref", "main", "--config", "x.toml",
                             "--check", CHECK)[0], 3)


class GuardTests(RepoCase):
    def guard(self) -> tuple[int, str]:
        code, out, _ = run("guard", self.root, "--base", "main")
        return code, out

    def test_real_fix_is_clean(self) -> None:
        self.write("src/a.ts", "const cfg = { claim_token: process.env.TOKEN };\n")
        self.assertEqual(self.guard()[0], 0)

    def test_policy_change_is_bypass(self) -> None:
        for rel in (".ruttla.toml", ".ruttla/baseline.toml", ".github/workflows/ci.yml",
                    "sub/.gitignore"):
            with self.subTest(rel=rel):
                self.git("checkout", "-q", "--", ".")
                self.git("clean", "-qfd")
                self.write(rel, "x = 1\n")
                code, out = self.guard()
                self.assertEqual(code, 1)
                self.assertIn(f"POLICY\t{rel}", out)

    def test_added_suppression_is_bypass(self) -> None:
        self.write("src/a.ts", "// eslint-disable-next-line\nconst cfg = {\n" + LINE + "};\n")
        code, out = self.guard()
        self.assertEqual(code, 1)
        self.assertIn("SUPPRESSION\tsrc/a.ts\t0 → 1", out)

    def test_removed_test_is_bypass_but_added_test_is_not(self) -> None:
        self.write("tests/test_a.py", "def test_one():\n    pass\n")
        code, out = self.guard()
        self.assertEqual(code, 1)
        self.assertIn("TESTS\ttests/test_a.py\t2 → 1", out)
        self.write("tests/test_a.py", "def test_one():\n    pass\n\ndef test_two():\n    pass\n"
                                      "\ndef test_three():\n    pass\n")
        self.assertEqual(self.guard()[0], 0)

    def test_deleted_test_file_is_bypass(self) -> None:
        os.remove(Path(self.root, "tests/test_a.py"))
        self.assertEqual(self.guard()[0], 1)

    def test_bad_base_is_exit_3(self) -> None:
        self.assertEqual(run("guard", self.root, "--base", "nope")[0], 3)

    def test_matchers(self) -> None:
        self.assertTrue(guard.is_test_file("src/FooTests.swift"))
        self.assertTrue(guard.is_test_file("web/a.spec.ts"))
        self.assertFalse(guard.is_test_file("src/contest.py"))
        self.assertFalse(guard.is_policy("docs/ruttla.toml.md"))



if __name__ == "__main__":
    unittest.main()
