"""Konformitäts-Kit für deklarative Regeln: ``ruttla rule test PFAD…`` (P10-T009).

Prüft eine Regeldatei oder ein Regelpaket (Verzeichnis) so, wie es der Hub
vor der Aufnahme tun wird — ohne Core-Repo, nur mit installiertem Paket und
Engine. Jede Regel wird **isoliert** geladen (eigene Kopie in einem leeren
Verzeichnis), damit eine kaputte Regel nicht die Nachbarn mitreißt und keine
offizielle Regel die Messung beeinflusst.

Prüfschritte, je einzeln gemeldet (eine Ablehnung verdeckt keine andere):

``schema``      Engine lädt die Regel (Format, Plattform, linearzeitiges
                Muster, Größengrenze, Pflicht-Fixtures beider Richtungen,
                ``fix`` mit Quelle, …).
``id``          Keine Kollision mit einem offiziellen Check, keine doppelte ID
                im Paket.
``fixtures``    Jede Fixture besteht.
``wirksamkeit`` Die Fixtures prüfen die Regel, nicht sich selbst: mit
                neutralisiertem Muster muss eine Fixture kippen, und ohne
                jeden einzelnen Ausschluss ebenfalls — sonst ist der
                Ausschluss eine ungeprüfte Freistellung.
``budget``      Laufzeit und Befundmenge je Datei auf erzeugten Stressdateien
                (Fixture-Inhalt wiederholt, als eine Zeile, Leerraum).

Kein Code aus der Regel wird ausgeführt; die Regel ist Daten, die Engine
führt nur ihr Muster aus (ADR-0005, ADR-0011).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .engine import EXIT_CRASH, EXIT_FAILED, EXIT_OK, EXIT_UNMEASURED

KIT_FORMAT = "ruttla-rulekit/0"

OK, REJECTED, UNMEASURED, WARNING = "ok", "abgelehnt", "nicht gemessen", "hinweis"
ACCEPTED = "angenommen"

# Größe jeder Stressdatei. Bleibt unter DEFAULT_MAX_FILE_BYTES der Engine
# (2 000 000), sonst würde die Datei übersprungen statt gemessen.
STRESS_BYTES = 1_000_000
STRESS_FILES = 3
# Laufzeitgrenze für den Scan der drei Stressdateien (Wanduhr, inkl.
# Prozessstart und JSON). Gemessen 2026-10-05 (aarch64): die sieben
# offiziellen Regeln 0,03–0,11 s (Release) bzw. 0,46–1,52 s (Debug-Build, den
# die Tests nehmen). Ein Muster, das jedes Zeichen trifft, brauchte vor dem
# Zeilen-Cache der Engine 22 s schon für 100 KB.
BUDGET_S = 10.0
# Engine-Ausgabe über dieser Größe gilt als Befundflut und wird nicht
# geparst. Gemessen 2026-10-05: offizielle Regeln höchstens 3,1 MB; eine
# Regel, die jedes Zeichen meldet, 612 MB nach 11 s (Release).
MAX_OUTPUT_BYTES = 64_000_000
SELFTEST_TIMEOUT_S = 120


class KitArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_CRASH, f"RUNNER_ERROR\tinvalid_arguments\t{message}\n")


@dataclass
class Step:
    step: str
    status: str
    detail: str = ""


@dataclass
class RuleReport:
    path: str
    id: str | None
    verdict: str = UNMEASURED
    steps: list[Step] = field(default_factory=list)

    def add(self, step: str, status: str, detail: str = "") -> None:
        self.steps.append(Step(step, status, detail))

    def decide(self) -> None:
        states = {s.status for s in self.steps}
        if REJECTED in states:
            self.verdict = REJECTED
        elif UNMEASURED in states or not self.steps:
            self.verdict = UNMEASURED
        else:
            self.verdict = ACCEPTED


# ---------------------------------------------------------------------------
# TOML schreiben (nur was das Regelformat braucht) — für die Mutationen
# ---------------------------------------------------------------------------

def _toml_str(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _toml_str(value)
    if isinstance(value, list) and all(not isinstance(v, dict) for v in value):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"nicht serialisierbar: {type(value).__name__}")


def dump_toml(data: dict, prefix: tuple[str, ...] = ()) -> str:
    """Schreibt Skalare, Tabellen und Tabellen-Arrays. Schlüssel immer in
    Anführungszeichen — Dateipfade in ``[fixtures.files]`` sind keine
    bloßen Schlüssel."""
    lines: list[str] = []
    tables: list[tuple[str, dict]] = []
    arrays: list[tuple[str, list[dict]]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            arrays.append((key, value))
        else:
            lines.append(f"{_toml_str(key)} = {_toml_value(value)}")
    for key, value in tables:
        path = (*prefix, key)
        lines.append(f"\n[{'.'.join(_toml_str(p) for p in path)}]")
        lines.append(dump_toml(value, path))
    for key, items in arrays:
        path = (*prefix, key)
        for item in items:
            lines.append(f"\n[[{'.'.join(_toml_str(p) for p in path)}]]")
            lines.append(dump_toml(item, path))
    return "\n".join(line for line in lines if line != "")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _run_engine(binary: Path, args: list[str], timeout: float) -> tuple[int | None, str, float]:
    """(Exit oder None bei Zeitüberschreitung, stdout, Sekunden). Ausgabe in
    eine Datei, nie in eine Pipe; deren Größe wird beim Warten überwacht, damit
    eine Befundflut nicht Hunderte MB auf die Platte schreibt."""
    with tempfile.TemporaryFile(mode="w+b") as out:
        start = time.perf_counter()
        proc = subprocess.Popen([str(binary), *args], stdout=out, stderr=subprocess.DEVNULL)
        try:
            while True:
                try:
                    code = proc.wait(timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    size = os.fstat(out.fileno()).st_size
                    if size > MAX_OUTPUT_BYTES:
                        proc.kill()
                        proc.wait()
                        return proc.returncode, f'{{"oversize": {size}}}', time.perf_counter() - start
                    if time.perf_counter() - start > timeout:
                        proc.kill()
                        proc.wait()
                        return None, "", time.perf_counter() - start
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        elapsed = time.perf_counter() - start
        out.seek(0)
        return code, out.read().decode("utf-8", "replace"), elapsed


def _json(raw: str) -> dict:
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _isolated(work: Path, name: str, text: str) -> Path:
    """Neues, leeres Regelverzeichnis mit genau dieser einen Datei."""
    rules = Path(tempfile.mkdtemp(prefix="rules-", dir=work))
    # Bytes, nicht Textmodus: unter Windows würde aus einem CRLF der
    # Regeldatei sonst \r\r\n, und TOML lehnt ein einzelnes \r ab.
    (rules / name).write_bytes(text.encode("utf-8"))
    return rules


def _selftest(binary: Path, rules: Path) -> tuple[list[dict] | None, str]:
    code, raw, _ = _run_engine(binary, ["selftest", "--rules", str(rules)], SELFTEST_TIMEOUT_S)
    data = _json(raw)
    if code is None:
        return None, f"Selbsttest nach {SELFTEST_TIMEOUT_S}s abgebrochen"
    if "cases" not in data:
        return None, (data.get("error") or {}).get("message", f"Engine Exit {code}")
    return data["cases"], ""


# ---------------------------------------------------------------------------
# Prüfschritte
# ---------------------------------------------------------------------------

def _official_ids() -> dict[str, bytes | None]:
    """ID → Bytes der offiziellen Regeldatei (None bei Python-Checks)."""
    from .declarative import rules_dir
    from .engine import load_checks
    from .registry import REGISTRY

    if not REGISTRY:
        load_checks()
    files = {p.stem: p.read_bytes() for p in rules_dir().rglob("*.toml")}
    return {cid: files.get(cid) for cid in REGISTRY}


def _check_schema(binary: Path, rules: Path, report: RuleReport) -> bool:
    code, raw, _ = _run_engine(binary, ["check-rules", "--rules", str(rules)], SELFTEST_TIMEOUT_S)
    data = _json(raw)
    if code == 0 and data.get("rules") == [report.id]:
        report.add("schema", OK)
        return True
    if code == 3 and (data.get("error") or {}).get("kind") == "rules":
        message = data["error"]["message"]
        # Pfad des Temp-Verzeichnisses aus der Meldung nehmen — er sagt dem
        # Einreicher nichts.
        message = "\n".join(line.split(": ", 1)[-1] for line in message.splitlines())
        report.add("schema", REJECTED, message)
        return False
    report.add("schema", UNMEASURED, f"Engine Exit {code}: {raw.strip()[:500]}")
    return False


def _check_fixtures(binary: Path, rules: Path, report: RuleReport) -> bool:
    cases, error = _selftest(binary, rules)
    if cases is None:
        report.add("fixtures", UNMEASURED, error)
        return False
    if not cases:
        report.add("fixtures", REJECTED, "null Fixtures gelaufen")
        return False
    bad = [c for c in cases if not c["ok"]]
    if bad:
        report.add("fixtures", REJECTED, "; ".join(
            f"{c['name']}: erwartet {c['expected']}, bekommen {c['got']}"
            + (f" ({c['detail']})" if c.get("detail") else "") for c in bad))
        return False
    report.add("fixtures", OK, f"{len(cases)} Fixtures grün")
    return True


def _mutants(rule: dict) -> list[tuple[str, dict]]:
    """Je eine Regel ohne den Teil, den eine Fixture belegen muss."""
    out = []
    neutral = json.loads(json.dumps(rule))
    # Ein Präfix, das nie vorkommt: Gruppen und Gültigkeit bleiben erhalten,
    # das Muster trifft nichts mehr.
    sentinel = f"RUTTLAKITNEUTRAL{uuid.uuid4().hex}"
    neutral["match"]["pattern"] = f"{sentinel}(?:{rule['match']['pattern']})"
    out.append(("Muster neutralisiert", neutral))
    for i, ex in enumerate(rule["match"].get("exclude", [])):
        mutant = json.loads(json.dumps(rule))
        del mutant["match"]["exclude"][i]
        if not mutant["match"]["exclude"]:
            del mutant["match"]["exclude"]
        on = ex.get("on", "match")
        out.append((f"Ausschluss #{i + 1} (on = {on}, pattern = {ex['pattern']!r}) entfernt", mutant))
    return out


def _check_effect(binary: Path, work: Path, name: str, rule: dict, report: RuleReport) -> None:
    uncovered, unmeasured = [], []
    for label, mutant in _mutants(rule):
        text = dump_toml(mutant)
        if tomllib.loads(text) != mutant:
            unmeasured.append(f"{label}: Mutation nicht verlustfrei schreibbar")
            continue
        cases, error = _selftest(binary, _isolated(work, name, text))
        if cases is None:
            unmeasured.append(f"{label}: {error}")
        elif all(c["ok"] for c in cases):
            uncovered.append(label)
    if uncovered:
        report.add("wirksamkeit", REJECTED,
                   "keine Fixture kippt bei: " + "; ".join(uncovered)
                   + " — dieser Teil der Regel ist ungeprüft (Fixture dafür ergänzen oder Teil streichen)")
    elif unmeasured:
        report.add("wirksamkeit", UNMEASURED, "; ".join(unmeasured))
    else:
        report.add("wirksamkeit", OK)


def stress_files(rule: dict) -> dict[str, str]:
    """Drei Dateien je ~STRESS_BYTES in der ersten Endung der Regel.

    Grundlage ist der Inhalt der grünen Fixtures: das ist Material nahe am
    Muster, das nicht treffen soll — der übliche Fall beim Scannen. Rote
    Fixtures wiederholt ergäben eine Trefferdichte, die es in echten Dateien
    nicht gibt, und das Budget mäße dann JSON statt Mustersuche. Eine Regel,
    die auf beliebigem Text trifft, flutet trotzdem (Ausgabegrenze).
    """
    scope = rule.get("scope", {})
    exts = scope.get("extensions") or [".txt"]
    ext = exts[0]
    samples = [content for fx in rule.get("fixtures", []) if fx.get("expect") == "pass"
               for path, content in fx.get("files", {}).items()
               if any(path.lower().endswith(e) for e in exts)]
    base = "\n".join(s for s in samples if s.strip()) or "x"
    base += "\n"
    # Ohne den Pflichttext würde keine Stressdatei geprüft (require_text).
    head = scope.get("require_text", "")
    head = head + "\n" if head else ""
    repeated = base * (STRESS_BYTES // max(len(base.encode()), 1) + 1)
    repeated = head + repeated.encode()[:STRESS_BYTES].decode("utf-8", "ignore")
    one_line = "".join(" " if ch in "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029" else ch for ch in repeated)
    return {
        f"stress_wiederholt{ext}": repeated,
        f"stress_eine_zeile{ext}": one_line,
        # Leerzeilen: die Eingabe, an der `(?:^|\n)\s*` in Pythons re
        # quadratisch wurde. Ohne Leerzeichen, sonst misst eine
        # Trailing-Whitespace-Regel hier zu Recht jede Zeile.
        f"stress_leerzeilen{ext}": head + "\n" * STRESS_BYTES,
    }


def _check_budget(binary: Path, work: Path, rules: Path, rule: dict, report: RuleReport) -> None:
    root = Path(tempfile.mkdtemp(prefix="stress-", dir=work))
    for name, content in stress_files(rule).items():
        target = root / name
        # Die Endung stammt aus der Regel. Die Engine lehnt Pfadzeichen darin
        # schon beim Laden ab; hier zweite Sperre, falls eine alte Engine läuft.
        if any(ch in name for ch in "/\\:\0") or target.resolve().parent != root.resolve():
            report.add("budget", REJECTED, f"Endung ergibt einen Pfad: {name!r}")
            return
        target.write_bytes(content.encode("utf-8"))
    code, raw, elapsed = _run_engine(
        binary, ["scan", str(root), "--rules", str(rules), "--view", "unscoped", "--threads", "1"],
        BUDGET_S)
    if code is None:
        report.add("budget", REJECTED, f"Scan über {STRESS_FILES} Stressdateien nach {BUDGET_S:.0f}s abgebrochen "
                   "— Grenze überschritten")
        return
    data = _json(raw)
    if "oversize" in data:
        report.add("budget", REJECTED, f"Engine-Ausgabe {data['oversize'] // 1_000_000} MB nach "
                   f"{elapsed:.1f}s — Befundflut (Grenze {MAX_OUTPUT_BYTES // 1_000_000} MB)")
        return
    results = data.get("results") or []
    if code != 0 or len(results) != 1:
        report.add("budget", UNMEASURED, f"Engine Exit {code}: {raw.strip()[:300]}")
        return
    result = results[0]
    examined = result.get("units_examined", 0)
    if examined != STRESS_FILES:
        # Null oder zu wenig geprüfte Stressdateien sind kein bestandenes Budget.
        report.add("budget", UNMEASURED,
                   f"{examined} von {STRESS_FILES} Stressdateien geprüft (require_text/Regeldatei-Erkennung?)")
        return
    per_file: dict[str, int] = {}
    for f in result.get("findings", []):
        per_file[f["file"]] = per_file.get(f["file"], 0) + 1
    detail = (f"{elapsed:.2f}s für {STRESS_FILES} × {STRESS_BYTES // 1000} KB, "
              f"{len(raw) // 1000} KB Ausgabe, höchstens {max(per_file.values(), default=0)} Befunde je Datei")
    # Über BUDGET_S bricht _run_engine ab (Zweig oben) — ein zweiter
    # Zeitvergleich hier war in der Sabotage-Runde wirkungslos.
    report.add("budget", OK, detail)


def test_rule(path: Path, binary: Path | None, official: dict[str, bytes | None],
              package_ids: dict[str, list[Path]], work: Path) -> RuleReport:
    raw = path.read_bytes()
    try:
        rule = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        report = RuleReport(str(path), None)
        report.add("schema", REJECTED, f"kein gültiges TOML: {exc}")
        report.decide()
        return report
    rule_id = rule.get("id") if isinstance(rule.get("id"), str) else None
    report = RuleReport(str(path), rule_id)

    if binary is None:
        report.add("schema", UNMEASURED, "ruttla-engine nicht gefunden (ruttla update oder RUTTLA_ENGINE_BIN)")
    rules = _isolated(work, path.name, raw.decode("utf-8"))
    loaded = binary is not None and _check_schema(binary, rules, report)

    # ID unabhängig vom Schema: eine Kollision ist auch bei kaputter Regel ein Befund.
    if rule_id is None:
        report.add("id", UNMEASURED, "keine id lesbar")
    else:
        clashes = []
        if rule_id in official and official[rule_id] != raw:
            clashes.append("offizieller Check gleicher ID")
        if len(package_ids.get(rule_id, [])) > 1:
            others = [str(p) for p in package_ids[rule_id] if p != path]
            clashes.append("doppelt im Paket: " + ", ".join(others))
        report.add("id", REJECTED if clashes else OK, "; ".join(clashes))

    if not loaded:
        report.add("fixtures", UNMEASURED, "Regel nicht geladen")
        report.add("wirksamkeit", UNMEASURED, "Regel nicht geladen")
        report.add("budget", UNMEASURED, "Regel nicht geladen")
    else:
        assert binary is not None
        if _check_fixtures(binary, rules, report):
            _check_effect(binary, work, path.name, rule, report)
        else:
            report.add("wirksamkeit", UNMEASURED, "Fixtures nicht grün — Mutation sagt dann nichts")
        _check_budget(binary, work, rules, rule, report)
    report.decide()
    return report


def collect(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.toml")))
        elif p.is_file():
            files.append(p)
    return files


def run_kit(paths: list[Path]) -> list[RuleReport]:
    from .declarative import find_engine

    files = collect(paths)
    binary = find_engine()
    official = _official_ids()
    package_ids: dict[str, list[Path]] = {}
    for f in files:
        try:
            rid = tomllib.loads(f.read_text(encoding="utf-8")).get("id")
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
        if isinstance(rid, str):
            package_ids.setdefault(rid, []).append(f)
    work = Path(tempfile.mkdtemp(prefix="ruttla-rulekit-"))
    try:
        return [test_rule(f, binary, official, package_ids, work) for f in files]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def exit_code(reports: list[RuleReport]) -> int:
    verdicts = {r.verdict for r in reports}
    if REJECTED in verdicts:
        return EXIT_FAILED
    if UNMEASURED in verdicts or not reports:
        return EXIT_UNMEASURED
    return EXIT_OK


def _text(reports: list[RuleReport]) -> str:
    out = []
    for r in reports:
        out.append(f"{r.verdict.upper():<15} {r.id or '?'}  ({r.path})")
        for s in r.steps:
            line = f"  {s.status:<15} {s.step}"
            if s.detail:
                line += f": {s.detail}"
            out.append(line)
    counts = {v: sum(r.verdict == v for r in reports) for v in (ACCEPTED, REJECTED, UNMEASURED)}
    out.append(f"{len(reports)} Regeln: " + ", ".join(f"{n} {v}" for v, n in counts.items()))
    return "\n".join(out)


def run_rule_command(argv: list[str], prog: str = "ruttla") -> int:
    parser = KitArgumentParser(prog=f"{prog} rule", description="Regeln prüfen (Konformitäts-Kit).")
    sub = parser.add_subparsers(dest="cmd", required=True, parser_class=KitArgumentParser)
    test = sub.add_parser("test", help="Regeldatei(en) oder Regelpaket prüfen")
    test.add_argument("paths", nargs="+", type=Path, metavar="PFAD")
    test.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    missing = [str(p) for p in args.paths if not p.exists()]
    if missing:
        parser.error(f"Pfad nicht gefunden: {', '.join(missing)}")
    if not collect(args.paths):
        # Null Regeln ist kein bestandener Lauf.
        parser.error("keine .toml-Regel unter den angegebenen Pfaden")
    reports = run_kit(args.paths)
    if args.format == "json":
        print(json.dumps({"format": KIT_FORMAT, "rules": [asdict(r) for r in reports]},
                         ensure_ascii=False, indent=2))
    else:
        print(_text(reports))
    return exit_code(reports)
