"""Lokale Nutzungsstatistik — Opt-in, Default AUS, nur auf diesem Rechner.

Was gespeichert wird: Scans (Zeit, Exit, Umfang, CI ja/nein), Zählwerte je
Regel und je Schwere, und je Befund ein Fingerabdruck für den Lebenszyklus.
Was NIE gespeichert wird: Quelltext, Evidenz, Meldungen, Secrets, Klartextpfade,
Repo-Namen. Ein Projekt ist eine lokale Zufalls-ID; Pfade gehen nur als HMAC
mit einem lokalen Salt ein, der die Datenbank nie verlässt.

Harte Verträge: Scan-Ergebnis, Exit-Code und Reporter sind mit und ohne
Statistik gleich. Ein Statistikfehler bricht nie einen Scan — er wird gefangen
und als genau eine Warnung auf stderr gemeldet.

Lebenszyklus je Fingerabdruck: neu · weiter vorhanden · wieder aufgetreten
(Regression) · behoben. „Verschwunden" ist nur dann „behoben", wenn der Scan
die Stelle nachweislich erneut geprüft hat (Regel gelaufen und gemessen, Datei
im Prüfbereich und noch im Inventar, kein Absturz). Sonst: unbestimmt.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import CheckResult, Status

SCHEMA_VERSION = 1
STATS_FORMAT = "ruttla-stats/1"
DB_NAME = "stats.sqlite3"
ENV_DIR = "RUTTLA_STATS_DIR"
PERIODS = ("7", "30", "90", "all")
EXIT_CRASH = 3  # wie engine.EXIT_CRASH; hier ohne Import, damit stats leicht bleibt

# Je Version die Anweisungen, die von der Vorgängerversion dorthin führen.
# Eine veröffentlichte Version wird nie geändert, nur eine neue angehängt.
MIGRATIONS: dict[int, list[str]] = {
    1: [
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE TABLE projects (id TEXT PRIMARY KEY, path_key TEXT NOT NULL UNIQUE,"
        " first_seen TEXT NOT NULL)",
        "CREATE TABLE scans (id INTEGER PRIMARY KEY, project_id TEXT NOT NULL"
        " REFERENCES projects(id), started TEXT NOT NULL, ci INTEGER NOT NULL,"
        " scope TEXT NOT NULL, exit_code INTEGER NOT NULL, tool_version TEXT NOT NULL,"
        " files_scanned INTEGER NOT NULL, checks_pass INTEGER NOT NULL,"
        " checks_fail INTEGER NOT NULL, checks_unmeasured INTEGER NOT NULL,"
        " checks_error INTEGER NOT NULL, f_error INTEGER NOT NULL,"
        " f_warning INTEGER NOT NULL, f_info INTEGER NOT NULL, blocking INTEGER NOT NULL,"
        " new INTEGER NOT NULL, persisting INTEGER NOT NULL, reappeared INTEGER NOT NULL,"
        " fixed INTEGER NOT NULL, indeterminate INTEGER NOT NULL)",
        "CREATE INDEX scans_started ON scans(started)",
        "CREATE TABLE scan_rules (scan_id INTEGER NOT NULL REFERENCES scans(id),"
        " check_id TEXT NOT NULL, platform TEXT NOT NULL, error_class TEXT NOT NULL,"
        " status TEXT NOT NULL, findings INTEGER NOT NULL, blocking INTEGER NOT NULL,"
        " f_error INTEGER NOT NULL, f_warning INTEGER NOT NULL, f_info INTEGER NOT NULL,"
        " new INTEGER NOT NULL, persisting INTEGER NOT NULL, reappeared INTEGER NOT NULL,"
        " fixed INTEGER NOT NULL, indeterminate INTEGER NOT NULL,"
        " PRIMARY KEY (scan_id, check_id))",
        "CREATE TABLE fingerprints (project_id TEXT NOT NULL, fp TEXT NOT NULL,"
        " check_id TEXT NOT NULL, platform TEXT NOT NULL, file_key TEXT NOT NULL,"
        " state TEXT NOT NULL CHECK (state IN ('open', 'fixed')),"
        " first_scan INTEGER NOT NULL, last_seen_scan INTEGER NOT NULL,"
        " reappeared INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (project_id, fp))",
    ],
}

LIFECYCLE = ("new", "persisting", "reappeared", "fixed", "indeterminate")
_DIGITS = re.compile(r"\d+")


class StatsError(RuntimeError):
    """Statistik nicht lesbar oder nicht schreibbar."""


# ---------------------------------------------------------------------------
# Ablageort
# ---------------------------------------------------------------------------

def data_dir() -> Path:
    """Benutzer-Datenverzeichnis je OS, ohne Fremdabhängigkeit (ADR-0002)."""
    override = os.environ.get(ENV_DIR)
    if override:
        return Path(override)
    home = Path.home()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", "")
        # XDG: ein relativer Wert ist ungültig und wird ignoriert.
        base = Path(xdg) if xdg and os.path.isabs(xdg) else home / ".local" / "share"
    return base / "ruttla"


def db_path() -> Path:
    return data_dir() / DB_NAME


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_ci() -> bool:
    value = os.environ.get("CI", "").strip().lower()
    return value not in ("", "0", "false", "no")


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=2.0, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if row is None:
        return 0
    value = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if value is None:
        raise StatsError("Statistik-Datenbank ohne schema_version — nicht von Ruttla.")
    try:
        return int(value[0])
    except ValueError as exc:
        raise StatsError(f"schema_version unlesbar: {value[0]!r}") from exc


def migrate(conn: sqlite3.Connection) -> int:
    """Bringt die Datenbank auf SCHEMA_VERSION. Eine neuere wird nie angefasst."""
    current = _schema_version(conn)
    target = max(MIGRATIONS)
    if current > target:
        raise StatsError(
            f"Statistik-Datenbank hat Schema {current}, diese Ruttla-Version kennt "
            f"höchstens {target} — ruttla update, nichts wurde geschrieben.")
    for version in range(current + 1, target + 1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES"
                         " ('schema_version', ?)", (str(version),))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return target


def _meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return None if row is None else row[0]


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))


def open_existing() -> sqlite3.Connection | None:
    """Vorhandene Datenbank öffnen und migrieren; fehlt sie, None (nichts anlegen)."""
    path = db_path()
    if not path.is_file():
        return None
    conn = _connect(path)
    try:
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def enabled(conn: sqlite3.Connection) -> bool:
    return _meta(conn, "enabled") == "1"


# ---------------------------------------------------------------------------
# Erfassung (Andockpunkt: Scan-Ende in cli.main)
# ---------------------------------------------------------------------------

def _key(salt: bytes, *parts: str) -> str:
    return hmac.new(salt, "\0".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def fingerprint(salt: bytes, check_id: str, rel: str | None, evidence: str | None,
                message: str, ordinal: int = 0) -> str:
    """HMAC über (Regel, relativer Pfad, normalisierte Evidenz) — ohne Zeilennummer.

    Ohne Evidenz zählt die Meldung mit Ziffern als Platzhalter, damit eine
    Zeilenangabe im Text den Abdruck nicht bei jeder Verschiebung ändert.
    `ordinal` trennt gleichlautende Befunde in derselben Datei (zweites
    `except:`): sonst fiele das Beheben eines von zweien nie als behoben auf.
    """
    if evidence and evidence.strip():
        basis = " ".join(evidence.split())
    else:
        basis = "msg:" + _DIGITS.sub("#", " ".join(message.split()))
    parts = [check_id, rel or "", basis] + ([str(ordinal)] if ordinal else [])
    return _key(salt, "finding", *parts)


def record_scan(ctx, results: list[CheckResult], exit_code: int,
                changed: list[str] | None) -> None:
    """Scan erfassen, falls aktiviert. Wirft nie; Fehler = eine Warnung auf stderr."""
    try:
        path = db_path()
        if not path.is_file():
            return  # Default: aus, und dann wird nichts angelegt oder gelesen
        conn = _connect(path)
        try:
            # Erst den Schalter lesen, dann migrieren: eine ausgeschaltete
            # Datenbank wird von einem Scan nie verändert.
            if _schema_version(conn) == 0 or not enabled(conn):
                return
            migrate(conn)
            if _inside(db_path(), Path(ctx.root)):
                raise StatsError("Statistik-Verzeichnis liegt im geprüften Repo — "
                                 f"{ENV_DIR} anders setzen.")
            _record(conn, ctx, results, exit_code, changed)
        finally:
            conn.close()
    except Exception as exc:  # Vertrag: Statistik bricht nie einen Scan
        print(f"ruttla: Statistik nicht geschrieben ({type(exc).__name__}: {exc}). "
              "Der Scan ist davon unberührt.", file=sys.stderr)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return (root / ".git").exists()


def _record(conn: sqlite3.Connection, ctx, results: list[CheckResult], exit_code: int,
            changed: list[str] | None) -> None:
    salt = bytes.fromhex(_meta(conn, "salt") or "")
    if len(salt) < 16:
        raise StatsError("lokaler Salt fehlt — stats disable und enable neu.")
    started = _iso(_now())

    measured = {r.check_id for r in results if r.status in (Status.PASS, Status.FAIL)}
    seen: dict[str, tuple[CheckResult, str]] = {}
    per_rule: dict[str, dict[str, int]] = {}
    sev_total = {"error": 0, "warning": 0, "info": 0}
    blocking_total = 0
    for r in results:
        counts = per_rule.setdefault(r.check_id, {k: 0 for k in LIFECYCLE})
        counts.update({"findings": len(r.findings), "error": 0, "warning": 0, "info": 0,
                       "blocking": 0})
        ordinals: dict[str, int] = {}
        for f in sorted(r.findings, key=lambda f: (f.file or "", f.line or 0)):
            counts[f.severity.value] += 1
            sev_total[f.severity.value] += 1
            if f.blocking:
                counts["blocking"] += 1
                blocking_total += 1
            base = fingerprint(salt, r.check_id, f.file, f.evidence, f.message)
            ordinal = ordinals.get(base, 0)
            ordinals[base] = ordinal + 1
            fp = fingerprint(salt, r.check_id, f.file, f.evidence, f.message, ordinal)
            seen.setdefault(fp, (r, _key(salt, "file", f.file) if f.file else ""))

    conn.execute("BEGIN IMMEDIATE")
    try:
        path_key = _key(salt, "project", os.path.realpath(ctx.root))
        row = conn.execute("SELECT id FROM projects WHERE path_key=?", (path_key,)).fetchone()
        if row is None:
            project_id = secrets.token_hex(8)
            conn.execute("INSERT INTO projects(id, path_key, first_seen) VALUES (?, ?, ?)",
                         (project_id, path_key, started))
        else:
            project_id = row[0]

        cur = conn.execute(
            "INSERT INTO scans(project_id, started, ci, scope, exit_code, tool_version,"
            " files_scanned, checks_pass, checks_fail, checks_unmeasured, checks_error,"
            " f_error, f_warning, f_info, blocking, new, persisting, reappeared, fixed,"
            " indeterminate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " 0, 0, 0, 0, 0)",
            (project_id, started, int(is_ci()), "full" if changed is None else "changed",
             exit_code, _tool_version(), ctx.coverage().files_scanned,
             *(sum(1 for r in results if r.status == s)
               for s in (Status.PASS, Status.FAIL, Status.UNMEASURED, Status.ERROR)),
             sev_total["error"], sev_total["warning"], sev_total["info"], blocking_total))
        scan_id = cur.lastrowid

        total = {k: 0 for k in LIFECYCLE}

        def count(kind: str, check_id: str) -> None:
            total[kind] += 1
            if check_id in per_rule:
                per_rule[check_id][kind] += 1

        known = {fp: (state, check_id, file_key) for fp, state, check_id, file_key in
                 conn.execute("SELECT fp, state, check_id, file_key FROM fingerprints"
                              " WHERE project_id=?", (project_id,))}
        for fp, (r, file_key) in seen.items():
            previous = known.get(fp)
            if previous is None:
                conn.execute(
                    "INSERT INTO fingerprints(project_id, fp, check_id, platform, file_key,"
                    " state, first_scan, last_seen_scan) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
                    (project_id, fp, r.check_id, r.platform, file_key, scan_id, scan_id))
                count("new", r.check_id)
            elif previous[0] == "fixed":
                conn.execute("UPDATE fingerprints SET state='open', last_seen_scan=?,"
                             " reappeared=reappeared+1 WHERE project_id=? AND fp=?",
                             (scan_id, project_id, fp))
                count("reappeared", r.check_id)
            else:
                conn.execute("UPDATE fingerprints SET last_seen_scan=? WHERE project_id=?"
                             " AND fp=?", (scan_id, project_id, fp))
                count("persisting", r.check_id)

        missing = [(fp, check_id, file_key) for fp, (state, check_id, file_key)
                   in known.items() if state == "open" and fp not in seen]
        if missing:
            covered = _covered_file_keys(salt, ctx, changed) if exit_code != EXIT_CRASH \
                else set()
            for fp, check_id, file_key in missing:
                confirmed = (exit_code != EXIT_CRASH and check_id in measured
                             and (file_key == "" or file_key in covered))
                if confirmed:
                    conn.execute("UPDATE fingerprints SET state='fixed' WHERE project_id=?"
                                 " AND fp=?", (project_id, fp))
                    count("fixed", check_id)
                else:
                    count("indeterminate", check_id)

        conn.execute("UPDATE scans SET new=?, persisting=?, reappeared=?, fixed=?,"
                     " indeterminate=? WHERE id=?",
                     (*(total[k] for k in LIFECYCLE), scan_id))
        for r in results:
            c = per_rule[r.check_id]
            conn.execute(
                "INSERT OR REPLACE INTO scan_rules(scan_id, check_id, platform, error_class,"
                " status, findings, blocking, f_error, f_warning, f_info, new, persisting,"
                " reappeared, fixed, indeterminate) VALUES"
                " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (scan_id, r.check_id, r.platform, r.check_id.split(".", 1)[0],
                 r.status.value, c["findings"], c["blocking"], c["error"], c["warning"],
                 c["info"], *(c[k] for k in LIFECYCLE)))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _covered_file_keys(salt: bytes, ctx, changed: list[str] | None) -> set[str]:
    """Dateien, die dieser Scan nachweislich gelesen hat: im Inventar und im Umfang.

    Gelöscht, zu groß, ignoriert oder außerhalb von --changed-only → nicht drin,
    ein dort verschwundener Befund bleibt unbestimmt.
    """
    rels = {f.rel for f in ctx.unscoped().all_files()}
    if changed is not None:
        rels &= set(changed)
    return {_key(salt, "file", rel) for rel in rels}


def _tool_version() -> str:
    from . import __version__

    return __version__


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------

def _since(period: str, now: datetime) -> str | None:
    return None if period == "all" else _iso(now - timedelta(days=int(period)))


def _where(since: str | None, alias: str = "s") -> tuple[str, tuple]:
    return (f"WHERE {alias}.started >= ?", (since,)) if since else ("", ())


def summary(conn: sqlite3.Connection, period: str = "30", now: datetime | None = None,
            top: int = 10) -> dict:
    """Aggregierte Sicht — enthält nur Zählwerte, Regel-IDs und Projekt-Zufalls-IDs."""
    now = now or _now()
    since = _since(period, now)
    where, params = _where(since)

    def totals(cond: str = "", extra: tuple = ()) -> dict:
        clause = where + (" AND " if where else "WHERE ") + cond if cond else where
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(files_scanned),0),"
            " COALESCE(SUM(checks_pass+checks_fail+checks_unmeasured+checks_error),0),"
            " COALESCE(SUM(f_error),0), COALESCE(SUM(f_warning),0),"
            " COALESCE(SUM(f_info),0), COALESCE(SUM(blocking),0),"
            " COALESCE(SUM(new),0), COALESCE(SUM(persisting),0),"
            " COALESCE(SUM(reappeared),0), COALESCE(SUM(fixed),0),"
            " COALESCE(SUM(indeterminate),0), COUNT(DISTINCT project_id),"
            f" COALESCE(SUM(exit_code=3),0) FROM scans s {clause}", params + extra).fetchone()
        keys = ("scans", "files_scanned", "checks_run", "error", "warning", "info",
                "blocking", *LIFECYCLE, "projects", "crashed_scans")
        out = dict(zip(keys, row))
        out["findings"] = out["error"] + out["warning"] + out["info"]
        return out

    def grouped(column: str) -> list[dict]:
        rows = conn.execute(
            f"SELECT r.{column}, COUNT(DISTINCT r.scan_id), SUM(r.status IN ('pass','fail')),"
            " SUM(r.findings), SUM(r.blocking), SUM(r.new), SUM(r.persisting),"
            " SUM(r.reappeared), SUM(r.fixed), SUM(r.indeterminate)"
            f" FROM scan_rules r JOIN scans s ON s.id = r.scan_id {where}"
            f" GROUP BY r.{column} ORDER BY SUM(r.findings) DESC, r.{column}", params)
        keys = ("name", "scans", "measured_runs", "findings", "blocking", *LIFECYCLE)
        return [dict(zip(keys, row)) for row in rows]

    projects = [dict(zip(("project", "scans", "findings", "blocking", *LIFECYCLE), row))
                for row in conn.execute(
                    "SELECT project_id, COUNT(*), SUM(f_error+f_warning+f_info),"
                    " SUM(blocking), SUM(new), SUM(persisting), SUM(reappeared), SUM(fixed),"
                    f" SUM(indeterminate) FROM scans s {where} GROUP BY project_id"
                    " ORDER BY COUNT(*) DESC, project_id", params)]
    open_now = conn.execute("SELECT COUNT(*) FROM fingerprints WHERE state='open'").fetchone()[0]
    rules = grouped("check_id")
    return {
        "format": STATS_FORMAT,
        "generated": _iso(now),
        "period_days": None if period == "all" else int(period),
        "since": since,
        "enabled": enabled(conn),
        "enabled_at": _meta(conn, "enabled_at"),
        "scans_by_period": {p: totals_for(conn, _since(p, now)) for p in PERIODS},
        "totals": totals(),
        "local": totals("s.ci = 0"),
        "ci": totals("s.ci = 1"),
        "open_fingerprints": open_now,
        "by_project": projects,
        "by_platform": grouped("platform"),
        "by_error_class": grouped("error_class"),
        "by_rule": rules[:top],
        "rules_total": len(rules),
        "notes": [
            "Nur Läufe ab Aktivierung; nichts hochgerechnet.",
            "behoben = Regel lief gemessen, Datei im Prüfbereich und noch vorhanden, "
            "Befund weg. Sonst unbestimmt.",
            "Projekte sind lokale Zufalls-IDs; Pfade und Repo-Namen werden nicht gespeichert.",
        ],
    }


def totals_for(conn: sqlite3.Connection, since: str | None) -> int:
    where, params = _where(since)
    return conn.execute(f"SELECT COUNT(*) FROM scans s {where}", params).fetchone()[0]


def _active(row: dict) -> bool:
    """Zeile mit Befunden oder Lebenszyklus-Bewegung — Nullzeilen nur im JSON."""
    return any(row.get(k) for k in ("findings", "fixed", "indeterminate"))


def render_text(data: dict) -> str:
    t, local, ci = data["totals"], data["local"], data["ci"]
    span = "gesamt" if data["period_days"] is None else f"letzte {data['period_days']} Tage"
    lines = [
        f"Ruttla-Statistik — {span} (Stand {data['generated']})",
        f"Status: {'aktiv' if data['enabled'] else 'aus'} · erfasst seit "
        f"{data['enabled_at'] or '—'}",
        "Scans 7/30/90/gesamt: " + " / ".join(
            str(data["scans_by_period"][p]) for p in PERIODS),
        "",
        f"Scans {t['scans']} (lokal {local['scans']} · CI {ci['scans']}) · Projekte "
        f"{t['projects']} · Dateien {t['files_scanned']} · Checks {t['checks_run']} · "
        f"abgestürzt {t['crashed_scans']}",
        f"Befunde {t['findings']} (Fehler {t['error']} · Warnung {t['warning']} · Info "
        f"{t['info']}) · blockierend {t['blocking']}",
        f"Lebenszyklus: neu {t['new']} · weiter vorhanden {t['persisting']} · wieder "
        f"aufgetreten {t['reappeared']} · behoben {t['fixed']} · unbestimmt "
        f"{t['indeterminate']} · offen jetzt {data['open_fingerprints']}",
    ]

    def table(title: str, rows: list[dict], name_key: str) -> None:
        rows = [row for row in rows if _active(row)]
        if not rows:
            return
        lines.extend(["", title])
        for row in rows:
            lines.append(
                f"  {str(row[name_key]):<44} Scans {row['scans']:>4} · Befunde "
                f"{row['findings'] or 0:>5} · neu {row['new'] or 0} · behoben "
                f"{row['fixed'] or 0} · wieder {row['reappeared'] or 0}")

    table("Je Projekt (lokale ID)", data["by_project"], "project")
    table("Je Paket", data["by_platform"], "name")
    table("Je Fehlerklasse", data["by_error_class"], "name")
    table(f"Je Regel (Top {len(data['by_rule'])} von {data['rules_total']})",
          data["by_rule"], "name")
    if not t["scans"]:
        lines.extend(["", "Keine Scans im Zeitraum."])
    return "\n".join(lines) + "\n"


def render_markdown(data: dict) -> str:
    t, local, ci = data["totals"], data["local"], data["ci"]
    span = "gesamt" if data["period_days"] is None else f"letzte {data['period_days']} Tage"
    out = [
        f"# Ruttla-Statistik — {span}", "",
        f"Stand {data['generated']} · erfasst seit {data['enabled_at'] or '—'} · "
        f"Format `{data['format']}`", "",
        "| Kennzahl | gesamt | lokal | CI |", "|---|---:|---:|---:|",
    ]
    for label, key in (("Scans", "scans"), ("Dateien", "files_scanned"),
                       ("Checks ausgeführt", "checks_run"), ("Befunde", "findings"),
                       ("blockierend", "blocking"), ("neu", "new"),
                       ("weiter vorhanden", "persisting"),
                       ("wieder aufgetreten", "reappeared"), ("behoben", "fixed"),
                       ("unbestimmt", "indeterminate")):
        out.append(f"| {label} | {t[key]} | {local[key]} | {ci[key]} |")

    def table(title: str, rows: list[dict], name_key: str) -> None:
        rows = [row for row in rows if _active(row)]
        if not rows:
            return
        out.extend(["", f"## {title}", "",
                    "| | Scans | Befunde | blockierend | neu | behoben | wieder |",
                    "|---|---:|---:|---:|---:|---:|---:|"])
        for row in rows:
            out.append(f"| `{row[name_key]}` | {row['scans']} | {row['findings'] or 0} | "
                       f"{row['blocking'] or 0} | {row['new'] or 0} | {row['fixed'] or 0} | "
                       f"{row['reappeared'] or 0} |")

    table("Je Projekt (lokale ID)", data["by_project"], "project")
    table("Je Paket", data["by_platform"], "name")
    table("Je Fehlerklasse", data["by_error_class"], "name")
    table(f"Je Regel (Top {len(data['by_rule'])} von {data['rules_total']})",
          data["by_rule"], "name")
    out.extend(["", "## Hinweise", ""] + [f"- {note}" for note in data["notes"]])
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI: ruttla stats …
# ---------------------------------------------------------------------------

def _parser(prog: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=f"{prog} stats",
        description="Lokale Nutzungsstatistik (Opt-in, Default aus, nur dieser Rechner). "
                    f"Ablage: {db_path()}",
        epilog="Exit: 0 ok · 3 Statistik nicht lesbar/schreibbar oder Fehlbedienung")
    sub = ap.add_subparsers(dest="action")
    for name in ("show", "export"):
        p = sub.add_parser(name, help="Dashboard" if name == "show"
                           else "JSON + Markdown in ein Verzeichnis schreiben")
        p.add_argument("--period", choices=PERIODS, default="30",
                       help="Tage oder all (Vorgabe 30)")
        p.add_argument("--top", type=int, default=10, help="Regeln in der Rangliste")
        if name == "show":
            p.add_argument("--format", choices=("text", "json", "markdown"), default="text")
        else:
            p.add_argument("--output-dir", default=".", help="Zielverzeichnis (Vorgabe .)")
    sub.add_parser("enable", help="Erfassung einschalten (Daten erst ab jetzt)")
    sub.add_parser("disable", help="Erfassung ausschalten, Daten bleiben")
    p = sub.add_parser("delete", help="Statistik-Datenbank unwiderruflich löschen")
    p.add_argument("--yes", action="store_true", help="ohne Rückfrage löschen")
    return ap


def run_stats_command(argv: list[str], prog: str = "ruttla") -> int:
    ap = _parser(prog)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["show", *argv]  # `ruttla stats --period 7` = show
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_CRASH
    action = args.action or "show"
    try:
        if action == "enable":
            return _enable()
        if action == "disable":
            return _disable()
        if action == "delete":
            return _delete(args.yes)
        return _show(args, action)
    except (StatsError, sqlite3.Error, OSError) as exc:
        print(f"ruttla stats: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_CRASH


def _enable() -> int:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fresh = not path.exists()
    conn = _connect(path)
    try:
        if fresh and os.name != "nt":
            os.chmod(path, 0o600)
        migrate(conn)
        if enabled(conn):
            print(f"Statistik ist schon aktiv: {path}")
            return 0
        if not _meta(conn, "salt"):
            _set_meta(conn, "salt", secrets.token_hex(32))
        _set_meta(conn, "enabled", "1")
        _set_meta(conn, "enabled_at", _iso(_now()))
    finally:
        conn.close()
    print(f"Statistik aktiv. Erfasst werden Scans ab jetzt, nur lokal: {path}")
    print("Gespeichert werden Zählwerte und Fingerabdrücke — kein Quelltext, keine Pfade, "
          "keine Repo-Namen.")
    return 0


def _disable() -> int:
    conn = open_existing()
    if conn is None:
        print("Statistik ist aus (keine Datenbank).")
        return 0
    try:
        _set_meta(conn, "enabled", "0")
    finally:
        conn.close()
    print(f"Statistik aus. Vorhandene Daten bleiben in {db_path()} — "
          "löschen mit: ruttla stats delete")
    return 0


def _delete(confirmed: bool) -> int:
    path = db_path()
    files = [p for p in (path, Path(f"{path}-journal"), Path(f"{path}-wal"),
                         Path(f"{path}-shm")) if p.exists()]
    if not files:
        print("Keine Statistik-Datenbank vorhanden.")
        return 0
    if not confirmed:
        if not sys.stdin.isatty():
            print(f"Löschen von {path} braucht --yes (kein Terminal für die Rückfrage).",
                  file=sys.stderr)
            return EXIT_CRASH
        answer = input(f"{path} unwiderruflich löschen? [j/N] ").strip().lower()
        if answer not in ("j", "ja", "y", "yes"):
            print("Nicht gelöscht.")
            return 0
    for p in files:
        p.unlink()
    print(f"Statistik gelöscht: {path}")
    return 0


def _show(args, action: str) -> int:
    conn = open_existing()
    if conn is None:
        print("Statistik ist aus — keine Daten. Einschalten: ruttla stats enable")
        return 0
    try:
        data = summary(conn, args.period, top=max(args.top, 0))
    finally:
        conn.close()
    if action == "export":
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        json_path, md_path = out / "ruttla-stats.json", out / "ruttla-stats.md"
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        md_path.write_text(render_markdown(data), encoding="utf-8")
        print(f"Exportiert: {json_path} · {md_path}")
    elif args.format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(render_markdown(data), end="")
    else:
        print(render_text(data), end="")
    return 0
