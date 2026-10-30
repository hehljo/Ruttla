"""`ruttla badge`: öffentliche Karte aus Vollscans — nur Zählwerte, nachprüfbarer Verlauf."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
for extra in (REPO / "src", REPO / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from ruttla import badge, cli, stats  # noqa: E402
from test_agent_setup import commands, problems  # noqa: E402

CHECK = "secrets.hardcoded_credential"
# Zur Laufzeit zusammengesetzt, damit diese Datei selbst keinen Befund trägt.
SECRET = hashlib.sha256(b"ruttla-badge").hexdigest()[:36]
LINE = "  claim_" + "token: '" + SECRET + "',\n"
DOC = REPO / "docs" / "integrations" / "stats-badge.md"


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def entry(**over) -> dict:
    base = {"schema": badge.CARD_SCHEMA, "recorded_at": "2026-10-30T00:00:00+00:00",
            "commit": None, "run_url": None, "ci": False, "ruttla_version": "1",
            "report_schema": "1.1", "exit_code": 0, "verdict": "passed", "rules_run": 3,
            "rules_digest": "d", "checks": {"pass": 3, "fail": 0, "unmeasured": 0, "error": 0},
            "files_scanned": 1, "platforms": [], "blocking": 0, "advisory": 0,
            "by_severity": {"error": 0, "warning": 0, "info": 0}, "by_check": {}}
    base.update(over)
    return base


class BadgeCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo, self.card = base / "repo", base / "card"
        (self.repo / "src").mkdir(parents=True)
        self.source = self.repo / "src" / "a.ts"
        self.source.write_text("const cfg = {\n" + LINE + "};\n", encoding="utf-8")
        # Die lokale Statistik des Nutzers bleibt unberührt.
        env = mock.patch.dict("os.environ", {stats.ENV_DIR: str(base / "stats")})
        env.start()
        self.addCleanup(env.stop)

    def update(self, *extra: str) -> tuple[int, str, str]:
        return run_cli("badge", "update", str(self.repo), "--dir", str(self.card), *extra)

    def history(self) -> list[dict]:
        return badge.load_history(self.card / badge.HISTORY)

    def read(self, name: str) -> dict:
        return json.loads((self.card / name).read_text(encoding="utf-8"))


class CardFromScanTests(BadgeCase):
    def test_finding_then_removal_is_counted_as_fewer(self) -> None:
        code, out, err = self.update("--project", "acme/app", "--commit", "c1")
        self.assertEqual(code, 0, err)
        self.assertGreater(self.history()[0]["blocking"], 0)
        self.assertEqual(self.read("badge.json")["color"], "red")
        self.assertIn(CHECK, self.history()[0]["by_check"])

        self.source.write_text("const cfg = {};\n", encoding="utf-8")
        code, _, err = self.update("--project", "acme/app", "--commit", "c2")
        self.assertEqual(code, 0, err)
        history = self.history()
        self.assertEqual(len(history), 2)
        totals = badge.totals(history)
        self.assertGreaterEqual(totals["findings_down"], 1)
        self.assertIn(CHECK, totals["rules_with_fewer_findings"])
        self.assertEqual(totals["blocking_now"], 0)
        self.assertEqual(totals["blocking_free_streak"], 1)
        self.assertEqual(self.read("badge.json")["color"], "brightgreen")
        self.assertEqual(self.read("badge-history.json")["message"][:7], "2 scans")
        summary = (self.card / badge.SUMMARY).read_text(encoding="utf-8")
        self.assertIn("acme/app", summary)
        self.assertIn(f"`{CHECK}`", summary)

    def test_nothing_private_is_published(self) -> None:
        self.update("--commit", "c1")
        published = "".join(p.read_text(encoding="utf-8") for p in self.card.iterdir())
        for private in (SECRET, str(self.repo), "a.ts", "claim_"):
            self.assertNotIn(private, published)

    def test_rerun_on_same_commit_is_not_counted_twice(self) -> None:
        self.update("--commit", "c1")
        code, out, _ = self.update("--commit", "c1")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.history()), 1)
        self.assertIn("nicht doppelt", out)
        # Ohne Commit ist jeder Lauf ein eigener Eintrag (lokale Nutzung).
        self.update()
        self.assertEqual(len(self.history()), 2)

    def test_scan_always_covers_everything(self) -> None:
        with mock.patch.object(cli, "main", wraps=cli.main) as spy:
            badge.scan(self.repo)
        argv = spy.call_args.args[0]
        self.assertNotIn("--changed-only", argv)
        self.assertEqual(argv[0], str(self.repo))

    def test_broken_history_stops_before_writing(self) -> None:
        self.card.mkdir()
        (self.card / badge.HISTORY).write_text("{kaputt\n", encoding="utf-8")
        code, _, err = self.update()
        self.assertEqual(code, 3)
        self.assertIn("history.jsonl:1", err)
        self.assertEqual((self.card / badge.HISTORY).read_text(encoding="utf-8"), "{kaputt\n")
        self.assertFalse((self.card / badge.STATUS).exists())

    def test_invalid_project_name_is_rejected(self) -> None:
        code, _, err = self.update("--project", "a\nb")
        self.assertEqual(code, 3)
        self.assertFalse(self.card.exists())

    def test_files_use_lf_only(self) -> None:
        self.update()
        for path in self.card.iterdir():
            self.assertNotIn(b"\r", path.read_bytes(), path.name)


class HistoryRuleTests(unittest.TestCase):
    def test_unmeasured_scan_is_not_history_and_not_green(self) -> None:
        history = [entry()]
        self.assertFalse(badge.append(history, entry(exit_code=2, commit="x")))
        self.assertEqual(len(history), 1)
        self.assertEqual(badge.badges(history, unmeasured=True)["badge.json"]["message"],
                         "not measured")
        self.assertEqual(badge.badges(history)["badge.json"]["color"], "brightgreen")

    def test_changed_version_or_rules_are_not_compared(self) -> None:
        for change in ({"ruttla_version": "2"}, {"rules_digest": "e"}):
            with self.subTest(change=change):
                history = [entry(advisory=5, by_check={"r": 5}),
                           entry(advisory=0, by_check={}, **change)]
                t = badge.totals(history)
                self.assertEqual((t["findings_down"], t["transitions_not_comparable"]), (0, 1))
        t = badge.totals([entry(advisory=5, by_check={"r": 5}), entry(advisory=2, by_check={"r": 2})])
        self.assertEqual((t["findings_down"], t["findings_up"]), (3, 0))

    def test_streak_counts_from_the_newest_scan(self) -> None:
        t = badge.totals([entry(), entry(blocking=1), entry(), entry()])
        self.assertEqual(t["blocking_free_streak"], 2)
        self.assertEqual(badge.totals([entry(), entry(blocking=1)])["blocking_free_streak"], 0)

    def test_foreign_report_is_rejected(self) -> None:
        for report in ({"tool_name": "other"}, {"tool_name": "ruttla", "schema_version": "2.0"},
                       {"tool_name": "ruttla", "schema_version": "1.1"}):
            with self.subTest(report=report), self.assertRaises(badge.CardError):
                badge.entry_from_report(report)

    def test_empty_history_renders_without_numbers(self) -> None:
        self.assertEqual(badge.badges([])["badge.json"]["message"], "not measured")
        self.assertIn("No measured scan", badge.render_summary([], None))


class CombineTests(BadgeCase):
    def test_combine_adds_up_cards(self) -> None:
        other = Path(self.tmp.name) / "card2"
        badge.write_card(other, [entry(advisory=4)], "acme/two", None)
        self.update("--project", "acme/one")
        out = Path(self.tmp.name) / "PROJECTS.md"
        code, _, err = run_cli("badge", "combine", str(self.card), str(other), "--out", str(out))
        self.assertEqual(code, 0, err)
        text = out.read_text(encoding="utf-8")
        self.assertIn("2 projects · 2 recorded scans", text)
        self.assertIn("| acme/one |", text)
        self.assertIn("| acme/two | 0 | 4 |", text)

    def test_combine_rejects_foreign_status(self) -> None:
        self.card.mkdir()
        (self.card / badge.STATUS).write_text('{"schema": "x"}', encoding="utf-8")
        code, _, _ = run_cli("badge", "combine", str(self.card), "--out",
                             str(Path(self.tmp.name) / "o.md"))
        self.assertEqual(code, 3)


class DocTests(unittest.TestCase):
    def test_documented_commands_exist(self) -> None:
        found = commands(DOC.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(found), 2, found)
        self.assertEqual({" ".join(t): p for t in found if (p := problems(t))}, {})
        self.assertTrue(problems(["badge", "update", ".", "--since", "x"]))


if __name__ == "__main__":
    unittest.main()
