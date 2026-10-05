"""Sabotage counter-probe of the gates themselves (``ruttla --self-test``).

Every check is exercised in BOTH directions: a broken probe must FAIL and a
healthy probe must PASS. Testing only broken data proves that a gate CAN go
red — not that it stays green on healthy data. A false-positive gate is
worse than none.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile

from .config import Config
from .context import Context
from .declarative import find_engine
from .engine import EXIT_FAILED, EXIT_OK, EXIT_UNMEASURED, validate_result
from .models import SelfTestCase, Status
from .registry import REGISTRY, Check
from .reporting.text import palette

# APIs, die es nicht gibt und die trotzdem naheliegend klingen. Jeder Eintrag
# gehört belegt (Doku/Feedback-ID), nicht vermutet.
NONEXISTENT_APIS: list[tuple[str, str]] = [
    (".system(size:relativeTo:)",
     "SwiftUI Font.system hat kein relativeTo — nur Font.custom(_:size:relativeTo:). "
     "FB9772279 ist ein offener Feature-Request. Compiler: "
     "\"Extra argument 'relativeTo' in call\"."),
]
# Legacy private name.
_NONEXISTENT_APIS = NONEXISTENT_APIS


def _materialise(work: str, files: dict[str, str]) -> bool:
    for rel, content in files.items():
        dest = os.path.abspath(os.path.join(work, rel))
        if os.path.commonpath((work, dest)) != work:
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    return True


def probe_count() -> int:
    return sum(len(check.self_tests) for check in REGISTRY.values())


def run_case(check: Check, case: SelfTestCase) -> str | None:
    """Eine Probe ausführen: None = Erwartung erfüllt, sonst die Abweichung."""
    work = os.path.realpath(tempfile.mkdtemp(prefix="ruttla-selftest-"))
    try:
        try:
            if not _materialise(work, case.files):
                raise ValueError("Testpfad verlässt Arbeitsbereich")
            ctx = Context(root=work, config=Config())
            res = validate_result(check, check.fn(ctx))
            okay = res.status == case.expect
            if okay and case.expect_finding_contains:
                blob = " ".join(
                    (f.message or "") + " " + (f.evidence or "")
                    for f in res.findings
                )
                okay = case.expect_finding_contains in blob
            if okay and case.expect_findings is not None and len(res.findings) != case.expect_findings:
                return f"{len(res.findings)} Befunde, erwartet {case.expect_findings}"
            if okay:
                return None
            extra = f" (reason: {res.reason})" if res.reason else ""
            return f"erwartet {case.expect.value}, bekommen {res.status.value}{extra}"
        except Exception as exc:
            return f"Probe abgestürzt: {type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


# Export der Proben als Daten (P11-T004): sie sind das Orakel für den Port
# nach Rust (ADR-0011). Ein portierter Check gilt erst, wenn er genau diese
# Proben unverändert besteht. Das Format ist eingefroren
# (schemas/selftests.schema.json); eine Änderung braucht einen neuen Namen.
SELFTEST_EXPORT_SCHEMA = "ruttla-selftests/1"
SELFTEST_INDEX = "index.json"


def _case_to_dict(case: SelfTestCase) -> dict:
    return {
        "name": case.name,
        "files": dict(sorted(case.files.items())),
        "expect": case.expect.value,
        "expect_finding_contains": case.expect_finding_contains,
    }


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


def export_self_tests(out_dir: str) -> int:
    """Je Check eine JSON-Datei plus Index; liefert die Probenzahl."""
    os.makedirs(out_dir, exist_ok=True)
    checks = []
    total = 0
    for check in sorted(REGISTRY.values(), key=lambda c: c.id):
        cases = [_case_to_dict(c) for c in check.self_tests]
        total += len(cases)
        _write_json(os.path.join(out_dir, f"{check.id}.json"), {
            "schema": SELFTEST_EXPORT_SCHEMA,
            "check_id": check.id,
            "platform": check.platform,
            "cases": cases,
        })
        checks.append({"check_id": check.id, "cases": len(cases)})
    _write_json(os.path.join(out_dir, SELFTEST_INDEX), {
        "schema": SELFTEST_EXPORT_SCHEMA,
        "checks": checks,
        "cases_total": total,
    })
    return total


def load_exported_self_tests(out_dir: str) -> dict[str, list[SelfTestCase]]:
    """Gegenstück zum Export; prüft Schema und Vollständigkeit gegen den Index."""
    with open(os.path.join(out_dir, SELFTEST_INDEX), encoding="utf-8") as fh:
        index = json.load(fh)
    if index.get("schema") != SELFTEST_EXPORT_SCHEMA:
        raise ValueError(f"unbekanntes Exportschema: {index.get('schema')!r}")
    loaded: dict[str, list[SelfTestCase]] = {}
    for entry in index["checks"]:
        cid = entry["check_id"]
        with open(os.path.join(out_dir, f"{cid}.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("schema") != SELFTEST_EXPORT_SCHEMA or data.get("check_id") != cid:
            raise ValueError(f"{cid}: Datei passt nicht zum Index")
        cases = [SelfTestCase(name=c["name"], files=c["files"], expect=Status(c["expect"]),
                              expect_finding_contains=c["expect_finding_contains"])
                 for c in data["cases"]]
        if len(cases) != entry["cases"]:
            raise ValueError(f"{cid}: {len(cases)} Proben, Index sagt {entry['cases']}")
        loaded[cid] = cases
    if sum(len(c) for c in loaded.values()) != index["cases_total"]:
        raise ValueError("Probensumme weicht vom Index ab")
    return loaded


def run_self_test(use_color: bool) -> int:
    """Jeder Check mit Sabotage-Proben wird in BEIDE Richtungen geprüft."""
    red, green, yellow, blue, grey, bold, reset = palette(use_color)
    total = passed = 0
    failures: list[str] = []
    without_tests: list[str] = []

    required_directions = {Status.PASS, Status.FAIL}
    # Deklarative Regeln laufen nur in der Engine. Fehlt sie, sind ihre Proben
    # NICHT GEMESSEN — nie still übersprungen und nie als bestanden gezählt.
    engine_missing = find_engine() is None
    not_run = 0
    for check in REGISTRY.values():
        if check.engine and engine_missing:
            not_run += len(check.self_tests)
            continue
        if not check.self_tests:
            without_tests.append(check.id)
            failures.append(f"{check.id}: keine Sabotage-Probe vorhanden.")
            continue
        directions = {c.expect for c in check.self_tests}
        missing = required_directions - directions
        if missing:
            names = ", ".join(sorted(status.value for status in missing))
            failures.append(
                f"{check.id}: Gegenrichtung fehlt ({names}) — erforderlich sind "
                "healthy=pass und negative=fail."
            )
        for case in check.self_tests:
            total += 1
            problem = run_case(check, case)
            if problem is None:
                passed += 1
            else:
                failures.append(f"{check.id} / '{case.name}': {problem}")
    # Ein fix:-Text ist Code, den jemand abschreibt. Empfiehlt er eine API,
    # die es nicht gibt, baut das Gate den Fehler ein, den es verhindern soll
    # — als Autorität, also schlimmer als gar kein Check.
    # Belegt am 18.09.2026: apple.hardcoded_font_size empfahl wörtlich
    # '.system(size:relativeTo:)'. Die gibt es nicht (FB9772279 ist ein offener
    # Feature-Request); der Vorschlag brach jeden Build, der ihm folgte.
    # Gemessen wird der Kandidat (alle fix:-Texte), nicht nur der Verstoß.
    fix_texts = 0
    # Je Fall ein eigenes Verzeichnis: mehrere Fälle teilen sich oft denselben
    # Dateipfad, und der PASS-Fall würde den FAIL-Fall überschreiben — dann
    # gibt es null Findings und damit null fix-Texte zu prüfen. Das Gate wäre
    # grün, ohne etwas gemessen zu haben.
    cases = [(c, case) for c in REGISTRY.values() for case in c.self_tests
             if not (c.engine and engine_missing)]
    for check, case in cases:
        work = os.path.realpath(tempfile.mkdtemp(prefix="ruttla-apicheck-"))
        try:
            if not _materialise(work, case.files):
                continue
            try:
                res = validate_result(
                    check, check.fn(Context(root=work, config=Config()))
                )
            except Exception:
                continue
            if res.status == Status.ERROR:
                continue
            for f in res.findings:
                if not f.fix:
                    continue
                fix_texts += 1
                low = f.fix.lower()
                for bad, why in NONEXISTENT_APIS:
                    # Eine Erwähnung, die das Nichtvorhandensein FESTSTELLT,
                    # ist kein Vorschlag — sonst löst die Dokumentation des
                    # Fehlers denselben Alarm aus wie der Fehler.
                    if bad.lower() not in low:
                        continue
                    idx = low.index(bad.lower())
                    window = low[max(0, idx - 60):idx]
                    if any(n in window for n in
                           ("kein", "nicht", "existiert nicht", "gibt es")):
                        continue
                    failures.append(
                        f"{check.id}: fix-Text empfiehlt '{bad}' — {why}"
                    )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    print(f"\n{bold}SABOTAGE-GEGENPROBE DER GATES{reset}\n")
    print(f"{len(REGISTRY)} Checks registriert, "
          f"{len(REGISTRY) - len(without_tests)} mit Sabotage-Proben.")
    print(f"{fix_texts} fix-Text(e) gegen {len(NONEXISTENT_APIS)} bekannte "
          f"Nicht-APIs geprüft.\n")
    for f in failures:
        print(f"  {red}✗{reset} {f}")
    if without_tests:
        print(f"\n{yellow}Ohne Sabotage-Probe ({len(without_tests)}):{reset}")
        for cid in without_tests:
            print(f"  {grey}· {cid}{reset}")
        print(f"{grey}  Ein Gate, das nie rot war, prüft nichts. Diese Checks "
              f"sind ungeprüfte Zusagen.{reset}")

    print("\n" + "─" * 70)
    if failures:
        print(f"{red}{bold}DURCHGEFALLEN{reset}: {passed}/{total} Proben bestanden, "
              f"{len(failures)} Problem(e).")
        return EXIT_FAILED
    if total == 0:
        print(f"{red}NICHT GEMESSEN: null Sabotage-Proben gelaufen.{reset}")
        return EXIT_UNMEASURED
    if not_run:
        print(f"{yellow}NICHT GEMESSEN{reset}: {passed}/{total} Proben bestanden, "
              f"{not_run} Proben deklarativer Regeln ohne ruttla-engine nicht gelaufen.")
        return EXIT_UNMEASURED
    print(f"{green}{bold}BESTANDEN{reset}: {passed}/{total} Sabotage-Proben, "
          f"beide Richtungen je Check.")
    return EXIT_OK
