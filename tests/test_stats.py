"""Lokale Statistik: Opt-in, Vertrag „Scan unverändert", Lebenszyklus, Datenschutz."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from ruttla import cli, stats  # noqa: E402

CHECK = "secrets.hardcoded_credential"
# Zur Laufzeit zusammengesetzt, damit diese Datei selbst keinen Befund trägt.
SECRET = hashlib.sha256(b"ruttla-stats").hexdigest()[:36]
LINE = "  claim_" + "token: '" + SECRET + "',\n"


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class StatsCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.stats_dir = base / "stats"
        self.repo = base / "repo"
        (self.repo / "src").mkdir(parents=True)
        self.write("src/a.ts", "const cfg = {\n" + LINE + "};\n")
        self.env = mock.patch.dict(os.environ, {stats.ENV_DIR: str(self.stats_dir)})
        self.env.start()
        os.environ.pop("CI", None)
        # Die Fixtures liegen selbst im Temp-Verzeichnis, das die Erfassung auslässt.
        self.throwaway = mock.patch.object(stats, "_throwaway_roots", return_value=[])
        self.throwaway.start()
        self.addCleanup(self.throwaway.stop)

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def scan(self, *extra: str) -> tuple[int, str, str]:
        return run_cli(str(self.repo), "--format", "json", "--check", CHECK, *extra)

    def lifecycle(self) -> dict:
        conn = sqlite3.connect(stats.db_path())
        try:
            row = conn.execute("SELECT new, persisting, reappeared, fixed, indeterminate"
                               " FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        return dict(zip(stats.LIFECYCLE, row))


class ContractTests(StatsCase):
    """Charakterisierung: Report und Exit byte-gleich mit und ohne Statistik."""

    def test_report_and_exit_identical_with_and_without_stats(self) -> None:
        off = self.scan()
        self.assertEqual(off[0], 1, off[2])
        self.assertFalse(self.stats_dir.exists(), "Default aus darf nichts anlegen")
        self.assertEqual(run_cli("stats", "enable")[0], 0)
        on = self.scan()
        self.assertEqual(on, off)
        self.assertEqual(self.lifecycle()["new"], 1, "Erfassung muss gelaufen sein")
        self.assertEqual(run_cli("stats", "disable")[0], 0)
        self.assertEqual(self.scan(), off)

    def test_text_and_agent_output_identical(self) -> None:
        for fmt in ("text", "agent", "sarif"):
            off = run_cli(str(self.repo), "--format", fmt, "--check", CHECK, "--no-color")
            run_cli("stats", "enable")
            on = run_cli(str(self.repo), "--format", fmt, "--check", CHECK, "--no-color")
            run_cli("stats", "disable")
            self.assertEqual(on, off, fmt)

    def test_scans_in_temp_dir_are_not_recorded(self) -> None:
        run_cli("stats", "enable")
        self.throwaway.stop()
        try:
            self.scan()
        finally:
            self.throwaway.start()
        conn = sqlite3.connect(stats.db_path())
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 0)
        conn.close()
        self.scan()
        self.assertEqual(self.lifecycle()["new"], 1)

    def test_disabled_db_is_not_touched_by_scan(self) -> None:
        run_cli("stats", "enable")
        run_cli("stats", "disable")
        before = stats.db_path().read_bytes()
        self.scan()
        self.assertEqual(stats.db_path().read_bytes(), before)

    def test_broken_db_never_breaks_scan(self) -> None:
        off = self.scan()
        self.stats_dir.mkdir()
        stats.db_path().write_bytes(b"kein sqlite" * 100)
        code, out, err = self.scan()
        self.assertEqual((code, out), off[:2])
        self.assertEqual(err.count("Statistik nicht geschrieben"), 1, err)

    def test_newer_schema_is_not_written(self) -> None:
        run_cli("stats", "enable")
        conn = sqlite3.connect(stats.db_path())
        conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        conn.commit()
        conn.close()
        code, out, err = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("Schema 99", err)
        conn = sqlite3.connect(stats.db_path())
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 0)
        conn.close()
        self.assertEqual(run_cli("stats")[0], 3)

    def test_crash_in_recording_is_one_warning(self) -> None:
        run_cli("stats", "enable")
        off_code = self.scan()[0]
        with mock.patch.object(stats, "_record", side_effect=RuntimeError("kaputt")):
            code, _, err = self.scan()
        self.assertEqual(code, off_code)
        self.assertEqual(err.count("Statistik nicht geschrieben"), 1)


class LifecycleTests(StatsCase):
    def setUp(self) -> None:
        super().setUp()
        run_cli("stats", "enable")

    def test_new_persisting_fixed_reappeared(self) -> None:
        self.scan()
        self.assertEqual(self.lifecycle()["new"], 1)
        # Zeilenverschiebung ändert den Abdruck nicht.
        self.write("src/a.ts", "// x\n// y\nconst cfg = {\n" + LINE + "};\n")
        self.scan()
        self.assertEqual(self.lifecycle()["persisting"], 1)
        self.write("src/a.ts", "const cfg = {};\n")
        self.assertEqual(self.scan()[0], 0)
        self.assertEqual(self.lifecycle()["fixed"], 1)
        self.write("src/a.ts", "const cfg = {\n" + LINE + "};\n")
        self.scan()
        self.assertEqual(self.lifecycle()["reappeared"], 1)

    def test_identical_findings_in_one_file_are_counted_apart(self) -> None:
        self.write("src/a.ts", "const a = {\n" + LINE + "};\nconst b = {\n" + LINE + "};\n")
        self.scan()
        self.assertEqual(self.lifecycle()["new"], 2)
        self.write("src/a.ts", "const a = {\n" + LINE + "};\n")
        self.scan()
        self.assertEqual((self.lifecycle()["persisting"], self.lifecycle()["fixed"]), (1, 1))

    def test_out_of_scope_is_indeterminate_not_fixed(self) -> None:
        self.scan()
        # Andere Regel ausgewählt → die alte lief nicht.
        run_cli(str(self.repo), "--format", "json", "--check", "secrets.credential_in_url")
        self.assertEqual(self.lifecycle()["indeterminate"], 1)
        self.assertEqual(self.lifecycle()["fixed"], 0)

    def test_crashed_scan_never_marks_fixed(self) -> None:
        self.scan()
        self.write("src/a.ts", "const cfg = {};\n")
        with mock.patch.object(cli, "apply_exit_policy", return_value=3):
            self.assertEqual(self.scan()[0], 3)
        self.assertEqual((self.lifecycle()["fixed"], self.lifecycle()["indeterminate"]), (0, 1))

    def test_deleted_file_is_indeterminate(self) -> None:
        self.scan()
        (self.repo / "src" / "a.ts").unlink()
        self.write("src/b.ts", "export const ok = 1;\n")
        self.scan()
        self.assertEqual(self.lifecycle()["indeterminate"], 1)
        self.assertEqual(self.lifecycle()["fixed"], 0)

    def test_changed_only_outside_scope_is_indeterminate(self) -> None:
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        import subprocess

        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-qm", "init"], check=True)
        self.scan()
        self.write("src/b.ts", "export const ok = 1;\n")
        self.scan("--changed-only")
        self.assertEqual(self.lifecycle()["indeterminate"], 1)
        self.assertEqual(self.lifecycle()["fixed"], 0)

    def test_ci_runs_counted_separately(self) -> None:
        self.scan()
        with mock.patch.dict(os.environ, {"CI": "true"}):
            self.scan()
        code, out, _ = run_cli("stats", "show", "--format", "json", "--period", "all")
        data = json.loads(out)
        self.assertEqual((code, data["local"]["scans"], data["ci"]["scans"]), (0, 1, 1))

    def test_db_holds_no_source_path_or_repo_name(self) -> None:
        self.scan()
        conn = sqlite3.connect(stats.db_path())
        dump = "\n".join(conn.iterdump())
        conn.close()
        for secret in (SECRET, "src/a.ts", "a.ts", str(self.repo), self.repo.name,
                       "claim_" + "token"):
            self.assertNotIn(secret, dump)
        self.assertIn(CHECK, dump)

    def test_export_and_delete(self) -> None:
        self.scan()
        out_dir = Path(self.tmp.name) / "export"
        self.assertEqual(run_cli("stats", "export", "--output-dir", str(out_dir))[0], 0)
        data = json.loads((out_dir / "ruttla-stats.json").read_text(encoding="utf-8"))
        self.assertEqual((data["format"], data["totals"]["scans"]), (stats.STATS_FORMAT, 1))
        self.assertIn(CHECK, (out_dir / "ruttla-stats.md").read_text(encoding="utf-8"))
        self.assertRegex(run_cli("stats")[1], r"Scans +1 ")
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            self.assertEqual(run_cli("stats", "delete")[0], 3)
        self.assertTrue(stats.db_path().exists())
        self.assertEqual(run_cli("stats", "delete", "--yes")[0], 0)
        self.assertFalse(stats.db_path().exists())


class LifetimeTests(StatsCase):
    """Bilanz: verschiedene Probleme über alle Läufe, nie Befunde je Scan aufsummiert."""

    def setUp(self) -> None:
        super().setUp()
        run_cli("stats", "enable")

    def life(self) -> dict:
        conn = sqlite3.connect(stats.db_path())
        try:
            return stats.summary(conn, "7")["lifetime"]
        finally:
            conn.close()

    def test_no_scan_is_not_measured(self) -> None:
        self.assertEqual(self.life()["scans"], 0)
        code, out, _ = run_cli("stats")
        self.assertEqual(code, 0)
        self.assertIn("Bilanz: nicht gemessen", out)

    def test_repeated_finding_counts_once(self) -> None:
        for _ in range(3):
            self.scan()
        life = self.life()
        self.assertEqual((life["scans"], life["found"], life["open"], life["fixed"]), (3, 1, 1, 0))
        self.assertEqual(life["scans_blocking"], 3)
        self.assertEqual(life["found_by_period"], {"7": 1, "30": 1, "90": 1, "all": 1})

    def test_fixed_regression_and_percent(self) -> None:
        self.write("src/a.ts", "const a = {\n" + LINE + "};\nconst b = {\n" + LINE + "};\n")
        self.scan()
        self.write("src/a.ts", "const a = {\n" + LINE + "};\n")
        self.scan()
        life = self.life()
        self.assertEqual((life["found"], life["fixed"], life["open"], life["fixed_percent"]),
                         (2, 1, 1, 50))
        self.write("src/a.ts", "const a = {\n" + LINE + "};\nconst b = {\n" + LINE + "};\n")
        self.scan()
        life = self.life()
        self.assertEqual((life["found"], life["regressions"], life["open"]), (2, 1, 2))

    def test_lifetime_ignores_selected_period(self) -> None:
        self.scan()
        conn = sqlite3.connect(stats.db_path())
        try:
            conn.execute("UPDATE scans SET started='2020-01-01T00:00:00Z'")
            conn.commit()
            data = stats.summary(conn, "7")
        finally:
            conn.close()
        self.assertEqual(data["totals"]["scans"], 0)
        self.assertEqual(data["lifetime"]["found"], 1)
        self.assertEqual(data["lifetime"]["found_by_period"]["90"], 0)

    def test_dashboard_and_markdown_show_balance(self) -> None:
        self.scan()
        _, out, _ = run_cli("stats")
        self.assertIn("Probleme gefunden  1 verschiedene", out)
        self.assertLess(out.index("Bilanz seit"), out.index("Scans "))
        _, md, _ = run_cli("stats", "--format", "markdown")
        self.assertIn("## Bilanz", md)
        self.assertIn("davon behoben      0 (0 %)", md)


class MigrationTests(StatsCase):
    def test_upgrade_keeps_data(self) -> None:
        run_cli("stats", "enable")
        self.scan()
        extra = {**stats.MIGRATIONS, 2: ["ALTER TABLE scans ADD COLUMN note TEXT"]}
        with mock.patch.object(stats, "MIGRATIONS", extra):
            self.scan()
            conn = sqlite3.connect(stats.db_path())
            version = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
            self.assertEqual(version.fetchone()[0], "2")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 2)
            conn.close()

    def test_failed_migration_rolls_back(self) -> None:
        run_cli("stats", "enable")
        broken = {**stats.MIGRATIONS, 2: ["ALTER TABLE scans ADD COLUMN x TEXT",
                                           "KAPUTT"]}
        with mock.patch.object(stats, "MIGRATIONS", broken):
            code, _, err = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("Statistik nicht geschrieben", err)
        conn = sqlite3.connect(stats.db_path())
        cols = [r[1] for r in conn.execute("PRAGMA table_info(scans)")]
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        conn.close()
        self.assertNotIn("x", cols)
        self.assertEqual(version[0], "1")
        # Dieselbe Verbindung danach: ohne ROLLBACK stünde die halbe Migration offen.
        conn = sqlite3.connect(stats.db_path(), isolation_level=None)
        with mock.patch.object(stats, "MIGRATIONS", broken), \
                self.assertRaises(sqlite3.OperationalError):
            stats.migrate(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(scans)")]
        conn.close()
        self.assertNotIn("x", cols)


class FingerprintTests(unittest.TestCase):
    def test_line_numbers_and_whitespace_do_not_change_fingerprint(self) -> None:
        salt = b"s" * 32
        fp = stats.fingerprint
        self.assertEqual(fp(salt, "r", "a.py", None, "Zeile 12: x fehlt"),
                         fp(salt, "r", "a.py", None, "Zeile 40:  x fehlt"))
        self.assertEqual(fp(salt, "r", "a.py", "a  =\tb", ""), fp(salt, "r", "a.py", "a = b", ""))
        self.assertNotEqual(fp(salt, "r", "a.py", "a = b", ""), fp(salt, "r", "b.py", "a = b", ""))
        self.assertNotEqual(fp(salt, "r", "a.py", "a = b", ""), fp(b"t" * 32, "r", "a.py", "a = b", ""))


class DataDirTests(unittest.TestCase):
    def data_dir(self, platform: str, env: dict) -> Path:
        # Eigenes Home und leere Umgebung: läuft so auf jedem Runner-OS gleich.
        home = Path(os.path.abspath("home-fixture"))
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(stats.Path, "home", return_value=home), \
                mock.patch.object(stats.sys, "platform", platform):
            return stats.data_dir().relative_to(home) if not env else stats.data_dir()

    def test_platform_defaults(self) -> None:
        xdg = os.path.abspath("xdg-fixture")
        self.assertEqual(self.data_dir("linux", {}), Path(".local/share/ruttla"))
        self.assertEqual(self.data_dir("linux", {"XDG_DATA_HOME": "relativ"}),
                         Path(os.path.abspath("home-fixture")) / ".local/share/ruttla")
        self.assertEqual(self.data_dir("linux", {"XDG_DATA_HOME": xdg}),
                         Path(xdg) / "ruttla")
        self.assertEqual(self.data_dir("darwin", {}),
                         Path("Library/Application Support/ruttla"))
        self.assertEqual(self.data_dir("win32", {}), Path("AppData/Roaming/ruttla"))
        self.assertEqual(self.data_dir("win32", {"APPDATA": xdg}), Path(xdg) / "ruttla")
        self.assertEqual(self.data_dir("linux", {stats.ENV_DIR: xdg}), Path(xdg))



class LifecycleReportTests(StatsCase):
    """`--lifecycle`: Anhang am Textreport; ohne Erfassung „nicht gemessen"."""

    def text(self, *extra: str) -> tuple[int, str, str]:
        return run_cli(str(self.repo), "--check", CHECK, "--no-color", *extra)

    def test_report_itself_is_unchanged(self) -> None:
        run_cli("stats", "enable")
        plain = self.text()
        with_lc = self.text("--lifecycle")
        self.assertEqual(with_lc[0], plain[0])
        self.assertTrue(with_lc[1].startswith(plain[1]), "Report vor dem Anhang muss gleich sein")
        self.assertIn("Lebenszyklus (lokale Statistik)", with_lc[1][len(plain[1]):])

    def test_off_is_not_measured_and_creates_nothing(self) -> None:
        code, out, _ = self.text("--lifecycle")
        self.assertEqual(code, 1)
        self.assertIn("Lebenszyklus: nicht gemessen — lokale Statistik ist aus", out)
        self.assertNotIn("0 neu", out)
        self.assertFalse(self.stats_dir.exists())

    def test_throwaway_is_not_measured(self) -> None:
        run_cli("stats", "enable")
        self.throwaway.stop()
        try:
            out = self.text("--lifecycle")[1]
        finally:
            self.throwaway.start()
        self.assertIn("Lebenszyklus: nicht gemessen — Scans im Temp-Verzeichnis", out)

    def test_new_fixed_regression_named_per_rule(self) -> None:
        run_cli("stats", "enable")
        out = self.text("--lifecycle")[1]
        self.assertIn("1 neu · 0 weiter vorhanden · 0 wieder aufgetreten · 0 behoben", out)
        self.assertIn(f"Neu: {CHECK} (1)", out)
        self.write("src/a.ts", "const cfg = {};\n")
        out = self.text("--lifecycle")[1]
        self.assertIn("0 neu · 0 weiter vorhanden · 0 wieder aufgetreten · 1 behoben", out)
        self.assertIn(f"Behoben: {CHECK} (1)", out)
        self.write("src/a.ts", "const cfg = {\n" + LINE + "};\n")
        out = self.text("--lifecycle")[1]
        self.assertIn("1 wieder aufgetreten", out)
        self.assertIn(f"Regression: {CHECK} (1)", out)
        self.assertNotIn("Neu:", out)

    def test_indeterminate_is_explained(self) -> None:
        run_cli("stats", "enable")
        self.text()
        (self.repo / "src/a.ts").unlink()
        self.write("src/b.ts", "const ok = 1;\n")
        out = self.text("--lifecycle")[1]
        self.assertIn("0 behoben · 1 unbestimmt", out)
        self.assertIn("nicht als behoben gezählt", out)

    def test_machine_formats_reject_the_flag(self) -> None:
        for extra in (("--format", "json"), ("--format", "agent"), ("--format", "sarif"),
                      ("--json",), ("--self-test",)):
            with self.subTest(extra=extra):
                code, out, err = run_cli(str(self.repo), "--lifecycle", *extra)
                self.assertEqual(code, 3)
                self.assertIn("invalid_arguments", out + err)


if __name__ == "__main__":
    unittest.main()
