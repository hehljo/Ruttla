"""Akzeptierte Befunde (`.ruttla/baseline.toml`) und Policy aus einer vertrauten Referenz.

Eine Ausnahme ist eine Entscheidung, keine Einstellung: jeder Eintrag nennt den
Befund per Fingerabdruck, wie oft er vorkommen darf, warum er bleibt und bis wann.
Abgelaufene Einträge unterdrücken nichts mehr. Die Datei wächst nie automatisch —
`baseline create` legt sie einmal an, danach kommt jeder Eintrag einzeln hinzu.

`--trusted-ref REF` liest Profil und Ausnahmen aus REF statt aus dem Arbeitsbaum:
ein Agent, der lokal eine Regel abschaltet oder eine Ausnahme einträgt, ändert
damit nichts an der Prüfung.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass

from .models import CheckResult, ConfigError, Status
from .reporting.sarif import fingerprint

BASELINE_PATH = ".ruttla/baseline.toml"
BASELINE_SCHEMA = "ruttla-baseline/1"
# Längste zulässige Laufzeit einer Ausnahme: ein Jahr. Länger heißt „für immer“,
# und das ist eine Regeländerung, keine Ausnahme.
MAX_DAYS = 366
POLICY_PROFILES = (".ruttla.toml", ".qualitygate.toml")
_ENTRY_KEYS = {"fingerprint", "check", "file", "count", "reason", "expires", "added"}


@dataclass
class Entry:
    fingerprint: str
    check: str
    file: str
    count: int
    reason: str
    expires: dt.date
    added: dt.date


# ---------------------------------------------------------------------------
# Vertraute Referenz
# ---------------------------------------------------------------------------

def verify_ref(root: str, ref: str) -> None:
    if not ref or ref.startswith("-") or "\0" in ref:
        raise ConfigError("Ungültige Git-Referenz für --trusted-ref.")
    try:
        probe = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "--quiet",
                                f"{ref}^{{commit}}"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigError(f"Git-Aufruf fehlgeschlagen: {exc}") from exc
    if probe.returncode != 0:
        raise ConfigError(f"--trusted-ref {ref}: Referenz nicht gefunden "
                          "(CI: fetch-depth 0 oder Basis-Branch holen).")


def read_at_ref(root: str, ref: str, rel: str) -> str | None:
    """Inhalt von ``rel`` (relativ zu ``root``) in ``ref``; None = dort nicht vorhanden."""
    try:
        listed = subprocess.run(["git", "-C", root, "ls-tree", "--name-only", ref, "--",
                                 rel], capture_output=True, timeout=30)
        if listed.returncode != 0:
            raise ConfigError(os.fsdecode(listed.stderr).strip() or f"git ls-tree {ref}")
        if not listed.stdout.strip():
            return None
        shown = subprocess.run(["git", "-C", root, "show", f"{ref}:./{rel}"],
                               capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigError(f"Git-Aufruf fehlgeschlagen: {exc}") from exc
    if shown.returncode != 0:
        raise ConfigError(os.fsdecode(shown.stderr).strip() or f"git show {ref}:{rel}")
    return shown.stdout.decode("utf-8")


def profile_at_ref(root: str, ref: str):
    """Profil aus ``ref`` — dieselben Regeln wie Config.load, nur aus Git gelesen."""
    from .config import Config

    found = {name: read_at_ref(root, ref, name) for name in POLICY_PROFILES}
    present = [name for name, text in found.items() if text is not None]
    if len(present) > 1:
        raise ConfigError(f"Zwei Profile in {ref}: {' und '.join(present)}.")
    if not present:
        return Config()
    try:
        data = tomllib.loads(found[present[0]])
    except ValueError as exc:
        raise ConfigError(f"Profil in {ref} nicht lesbar: {exc}") from exc
    return Config.from_mapping(data, profile_path=f"{ref}:{present[0]}")


def load_text(root: str, ref: str | None) -> str | None:
    if ref:
        return read_at_ref(root, ref, BASELINE_PATH)
    path = os.path.join(root, BASELINE_PATH)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

def parse(text: str, source: str = BASELINE_PATH) -> list[Entry]:
    try:
        data = tomllib.loads(text)
    except ValueError as exc:
        raise ConfigError(f"{source}: kein gültiges TOML: {exc}") from exc
    if set(data) - {"schema", "accepted"}:
        raise ConfigError(f"{source}: unbekannte Schlüssel "
                          + ", ".join(sorted(set(data) - {"schema", "accepted"})))
    if data.get("schema") != BASELINE_SCHEMA:
        raise ConfigError(f"{source}: schema muss {BASELINE_SCHEMA!r} sein.")
    raw = data.get("accepted", [])
    if not isinstance(raw, list):
        raise ConfigError(f"{source}: accepted muss eine Liste von Tabellen sein.")
    entries, seen = [], set()
    for i, item in enumerate(raw, 1):
        where = f"{source}: Eintrag {i}"
        if not isinstance(item, dict):
            raise ConfigError(f"{where}: keine Tabelle.")
        missing, unknown = _ENTRY_KEYS - set(item), set(item) - _ENTRY_KEYS
        if missing or unknown:
            raise ConfigError(f"{where}: fehlt {sorted(missing)} · unbekannt {sorted(unknown)}")
        for key in ("fingerprint", "check", "file", "reason"):
            if not isinstance(item[key], str):
                raise ConfigError(f"{where}: {key} muss Text sein.")
        if not item["reason"].strip():
            raise ConfigError(f"{where}: reason ist leer — eine Ausnahme braucht einen Grund.")
        count = item["count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ConfigError(f"{where}: count muss eine ganze Zahl ≥ 1 sein.")
        expires, added = item["expires"], item["added"]
        if not all(type(d) is dt.date for d in (expires, added)):
            raise ConfigError(f"{where}: expires und added müssen TOML-Daten sein "
                              "(2027-01-31, ohne Anführungszeichen).")
        if (expires - added).days > MAX_DAYS:
            raise ConfigError(f"{where}: Laufzeit über {MAX_DAYS} Tage — das ist keine "
                              "Ausnahme mehr, sondern eine Regeländerung im Profil.")
        if item["fingerprint"] in seen:
            raise ConfigError(f"{where}: Fingerabdruck doppelt.")
        seen.add(item["fingerprint"])
        entries.append(Entry(item["fingerprint"], item["check"], item["file"], count,
                             item["reason"], expires, added))
    return entries


def render(entries: list[Entry]) -> str:
    out = ["# Akzeptierte Befunde — Änderungen nur per Review, nie durch einen Agenten.",
           f'schema = "{BASELINE_SCHEMA}"', ""]
    for e in sorted(entries, key=lambda e: (e.check, e.file, e.fingerprint)):
        out += ["[[accepted]]",
                f"fingerprint = {json.dumps(e.fingerprint)}",
                f"check = {json.dumps(e.check)}",
                f"file = {json.dumps(e.file, ensure_ascii=False)}",
                f"count = {e.count}",
                f"reason = {json.dumps(e.reason, ensure_ascii=False)}",
                f"added = {e.added.isoformat()}",
                f"expires = {e.expires.isoformat()}", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Anwenden
# ---------------------------------------------------------------------------

def finding_fingerprint(f) -> str:
    return fingerprint({"check_id": f.check_id, "file": f.file, "evidence": f.evidence,
                        "message": f.message})


def apply(results: list[CheckResult], entries: list[Entry], today: dt.date) -> dict:
    """Nimmt akzeptierte Befunde aus den Ergebnissen. Ein Check ohne verbleibenden
    Befund gilt als bestanden; abgelaufene Einträge unterdrücken nichts."""
    active = {e.fingerprint: e for e in entries if e.expires >= today}
    budget = {fp: e.count for fp, e in active.items()}
    used = {fp: 0 for fp in active}
    suppressed = 0
    for r in results:
        if not r.findings:
            continue
        kept = []
        for f in r.findings:
            fp = finding_fingerprint(f)
            if budget.get(fp, 0) > 0:
                budget[fp] -= 1
                used[fp] += 1
                suppressed += 1
            else:
                kept.append(f)
        if len(kept) != len(r.findings):
            r.findings = kept
            if not kept and r.status == Status.FAIL:
                r.status = Status.PASS
    expired = [e for e in entries if e.expires < today]
    stale = [e for e in active.values() if used[e.fingerprint] == 0]
    return {
        "file": BASELINE_PATH, "entries": len(entries), "suppressed": suppressed,
        "expired": [{"check": e.check, "file": e.file, "expires": e.expires.isoformat()}
                    for e in expired],
        "stale": [{"check": e.check, "file": e.file} for e in stale],
    }


def summary_line(info: dict) -> str:
    line = (f"Ausnahmen ({info['file']}): {info['suppressed']} Befunde akzeptiert · "
            f"{len(info['expired'])} abgelaufen · {len(info['stale'])} ohne Befund")
    if info["expired"]:
        line += " — abgelaufene Ausnahmen zählen wieder als Befund"
    if info["stale"]:
        line += " — Einträge ohne Befund entfernen"
    return line


# ---------------------------------------------------------------------------
# CLI: ruttla baseline …
# ---------------------------------------------------------------------------

def _date(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"kein Datum (JJJJ-MM-TT): {text}") from exc


def _parser(prog: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=f"{prog} baseline",
        description=f"Akzeptierte Befunde in {BASELINE_PATH}: je Eintrag Fingerabdruck, "
                    "Anzahl, Grund und Ablaufdatum. Die Datei wächst nie automatisch.",
        epilog="Exit: 0 geschrieben · 1 nichts zu tun/abgelehnt · 3 Fehler")
    sub = ap.add_subparsers(dest="action", required=True)
    for name, help_text in (
            ("create", "einmalig: alle heutigen Befunde als Altlast aufnehmen "
                       "(nur, wenn noch keine Ausnahmen existieren)"),
            ("add", "die heutigen Befunde EINES Checks in EINER Datei aufnehmen")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("root", nargs="?", default=".", help="Projektwurzel (Vorgabe .)")
        p.add_argument("--reason", required=True, help="warum der Befund bleibt")
        p.add_argument("--expires", required=True, type=_date,
                       help=f"Ablaufdatum JJJJ-MM-TT (höchstens {MAX_DAYS} Tage)")
        if name == "add":
            p.add_argument("--check", required=True, help="Check-ID")
            p.add_argument("--file", required=True, help="Datei relativ zur Wurzel")
    p = sub.add_parser("show", help="Einträge mit Status (aktiv, abgelaufen, ohne Befund)")
    p.add_argument("root", nargs="?", default=".", help="Projektwurzel (Vorgabe .)")
    return ap


def _current_findings(root: str) -> list:
    from .config import Config
    from .context import Context
    from .engine import apply_exit_policy, load_checks, run_checks

    load_checks()
    config = Config.load(root)
    ctx = Context(root=root, config=config)
    results = run_checks(ctx, only_platform=None, only_checks=[], changed=None)
    apply_exit_policy(results, config)
    return [f for r in results if r.status == Status.FAIL for f in r.findings]


def _group(findings: list) -> dict[str, tuple]:
    grouped: dict[str, list] = {}
    for f in findings:
        grouped.setdefault(finding_fingerprint(f), []).append(f)
    return {fp: (fs[0], len(fs)) for fp, fs in grouped.items()}


def run_baseline_command(argv: list[str], prog: str = "ruttla") -> int:
    try:
        args = _parser(prog).parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    root = os.path.abspath(args.root)
    path = os.path.join(root, BASELINE_PATH)
    try:
        text = load_text(root, None)
        entries = parse(text) if text is not None else []
        today = dt.date.today()
        if args.action == "show":
            if text is None:
                print(f"Keine Ausnahmen ({BASELINE_PATH} fehlt).")
                return 0
            present = _group(_current_findings(root))
            for e in entries:
                state = ("abgelaufen" if e.expires < today else
                         "aktiv" if e.fingerprint in present else "ohne Befund")
                print(f"{state:<12} {e.check}  {e.file}  ×{e.count}  bis {e.expires}  "
                      f"— {e.reason}")
            return 0
        if (args.expires - today).days > MAX_DAYS or args.expires < today:
            print(f"--expires muss zwischen heute und {MAX_DAYS} Tagen liegen.",
                  file=sys.stderr)
            return 1
        if args.action == "create" and entries:
            print(f"{BASELINE_PATH} hat schon Einträge — einzeln mit `baseline add` "
                  "ergänzen. Die Altlast wird nur einmal aufgenommen.", file=sys.stderr)
            return 1
        found = _group(_current_findings(root))
        if args.action == "add":
            rel = args.file.replace("\\", "/")
            found = {fp: v for fp, v in found.items()
                     if v[0].check_id == args.check and (v[0].file or "") == rel}
        known = {e.fingerprint for e in entries}
        new = [Entry(fp, f.check_id, f.file or "", n, args.reason, args.expires, today)
               for fp, (f, n) in found.items() if fp not in known]
        if not new:
            print("Kein passender, noch nicht akzeptierter Befund — nichts geschrieben.",
                  file=sys.stderr)
            return 1
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(entries + new))
        print(f"{len(new)} Ausnahmen nach {BASELINE_PATH} geschrieben — per Review "
              "committen, nicht im selben Commit wie ein Fix.")
        return 0
    except ConfigError as exc:
        print(f"ruttla baseline: {exc}", file=sys.stderr)
        return 3
