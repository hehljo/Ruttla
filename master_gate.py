#!/usr/bin/env python3
"""
MASTER QUALITY GATE — universeller, tokenfreier Prüflauf über alle Guidelines.

Aufruf:
    python3 master_gate.py [VERZEICHNIS] [Optionen]

Die wichtigsten Optionen:
    --json [DATEI]      JSON-Report (ohne DATEI: auf stdout)
    --format agent      kompakter, KI-optimierter Text (Vorgabe bei --quiet)
    --platform NAME     nur diese Plattform (universal/apple/web/godot/raspberry)
    --check ID          nur diese Check-ID (mehrfach möglich, Präfix mit *)
    --list              alle Checks auflisten und beenden
    --self-test         Sabotage-Gegenprobe der Gates selbst
    --strict            jeder FAIL bricht ab, auch ohne Profil
    --changed-only REF  nur Dateien, die sich gegen REF geändert haben
    --max-findings N    je Check höchstens N Befunde ausgeben (Vorgabe 20)

Exit-Codes — der Vertrag mit der aufrufenden CLI:
    0  grün: alles bestanden, was gemessen werden konnte
    1  Fehler gefunden (mindestens ein Check auf error-Ebene durchgefallen)
    2  nichts gemessen: kein Check konnte laufen — NICHT als Erfolg werten
    3  Gate-Absturz oder Fehlbedienung

'Nicht gemessen' ist ein eigener Ausgang, nie stillschweigend grün. Warnungen
allein brechen nicht ab, erscheinen aber im Report.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import traceback
from dataclasses import asdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import (  # noqa: E402
    REGISTRY, ChangedFilesError, Check, CheckResult, Config, ConfigError, Context,
    Finding, GateInputError, Severity, Status, SCHEMA_VERSION,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNMEASURED = 2
EXIT_CRASH = 3

RED, GREEN, YELLOW, BLUE, GREY, BOLD, RESET = (
    "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[90m", "\033[1m", "\033[0m"
)


def _color(enabled: bool):
    if enabled:
        return RED, GREEN, YELLOW, BLUE, GREY, BOLD, RESET
    return ("",) * 7


class RunnerArgumentParser(argparse.ArgumentParser):
    """Argparse-Fehler gehören laut Runner-Vertrag zu Exit 3, nicht Exit 2."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_CRASH, f"RUNNER_ERROR\tinvalid_arguments\t{message}\n")


class PluginLoadError(RuntimeError):
    pass


def load_checks(checks_dir: str | None = None) -> None:
    """Lädt jedes Check-Modul und belegt, dass es mindestens einen Check
    registriert. Ein syntaktisch ladbares, aber leeres Plugin ist kein Lauf."""
    checks_dir = checks_dir or os.path.join(HERE, "checks")
    if not os.path.isdir(checks_dir):
        raise PluginLoadError(f"Check-Verzeichnis fehlt: {checks_dir}")
    candidates = [
        name for name in sorted(os.listdir(checks_dir))
        if name.endswith(".py") and not name.startswith("_")
    ]
    if not candidates:
        raise PluginLoadError("Null Check-Module gefunden — der Runner prüft nichts.")

    registered = 0
    for name in candidates:
        path = os.path.join(checks_dir, name)
        module_name = f"qg_checks_{name[:-3]}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Plugin nicht ladbar: {name}")
        before = set(REGISTRY)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            for check_id in set(REGISTRY) - before:
                REGISTRY.pop(check_id, None)
            sys.modules.pop(module_name, None)
            raise PluginLoadError(
                f"Plugin fehlgeschlagen: {name}: {type(exc).__name__}: {exc}"
            ) from exc
        added = set(REGISTRY) - before
        if not added:
            sys.modules.pop(module_name, None)
            raise PluginLoadError(f"Plugin registriert keinen Check: {name}")
        registered += len(added)
    if registered == 0:
        raise PluginLoadError("Null Checks registriert — der Runner prüft nichts.")


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------

def _crashed_check(check: Check, reason: str) -> CheckResult:
    return CheckResult(
        check.id, Status.ERROR, check.title, reason=reason, platform=check.platform,
    )


def _validate_result(check: Check, result: object) -> CheckResult:
    if not isinstance(result, CheckResult):
        return _crashed_check(
            check, f"Ungültiges Plugin-Ergebnis: {type(result).__name__} statt CheckResult."
        )
    if result.check_id != check.id:
        return _crashed_check(
            check, f"Plugin-Ergebnis trägt falsche Check-ID: {result.check_id!r}."
        )
    if not isinstance(result.status, Status):
        return _crashed_check(check, f"Ungültiger Check-Status: {result.status!r}.")
    if result.status == Status.UNMEASURED and not result.reason:
        return _crashed_check(check, "UNMEASURED ohne reason ist kein gültiges Ergebnis.")
    if result.status == Status.ERROR and not result.reason:
        return _crashed_check(check, "ERROR ohne reason ist kein gültiges Ergebnis.")
    if result.status in (Status.PASS, Status.FAIL) and result.units_examined <= 0:
        return _crashed_check(
            check, "PASS/FAIL mit null geprüften Einheiten ist kein gültiges Ergebnis."
        )
    if result.status == Status.FAIL and not result.findings:
        return _crashed_check(check, "FAIL ohne Befund ist kein gültiges Ergebnis.")
    return result


def run_checks(ctx: Context, *, only_platform: str | None,
               only_checks: list[str], changed: list[str] | None) -> list[CheckResult]:
    results: list[CheckResult] = []
    platforms = ctx.platforms()
    for check in REGISTRY.values():
        if only_platform and check.platform != only_platform:
            continue
        if only_checks and not any(
            check.id == c or (c.endswith("*") and check.id.startswith(c[:-1]))
            for c in only_checks
        ):
            continue
        if not only_platform and not only_checks and check.platform not in platforms:
            continue
        try:
            severity = ctx.config.severity_for(check.id, check.default_severity)
            if severity is None:
                continue  # im Profil abgeschaltet
            res = _validate_result(check, check.fn(ctx))
        except Exception:
            res = _crashed_check(
                check, "Check abgestürzt:\n" + traceback.format_exc(limit=4)
            )
        # Die Schwere aus dem Profil überschreibt die der Befunde.
        for f in res.findings:
            if f.severity != Severity.INFO or severity == Severity.ERROR:
                f.severity = severity
            f.guideline = f.guideline or check.guideline
        if changed is not None:
            keep = [f for f in res.findings if f.file is None or f.file in changed]
            if res.findings and not keep:
                res.status = Status.PASS
            res.findings = keep
        results.append(res)
    return results


def worst_exit(results: list[CheckResult]) -> int:
    if any(r.status == Status.ERROR for r in results):
        return EXIT_CRASH
    has_error_finding = any(
        f.severity == Severity.ERROR
        for r in results if r.status == Status.FAIL
        for f in r.findings
    )
    if has_error_finding:
        return EXIT_FAILED
    measured = [r for r in results if r.status in (Status.PASS, Status.FAIL)]
    if not measured:
        return EXIT_UNMEASURED
    return EXIT_OK


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def build_report(ctx: Context, results: list[CheckResult], exit_code: int,
                 max_findings: int) -> dict:
    counts = {
        "pass": sum(1 for r in results if r.status == Status.PASS),
        "fail": sum(1 for r in results if r.status == Status.FAIL),
        "unmeasured": sum(1 for r in results if r.status == Status.UNMEASURED),
        "error": sum(1 for r in results if r.status == Status.ERROR),
    }
    sev = {"error": 0, "warning": 0, "info": 0}
    for r in results:
        for f in r.findings:
            sev[f.severity.value] += 1

    verdict = {
        EXIT_OK: "green",
        EXIT_FAILED: "failed",
        EXIT_UNMEASURED: "unmeasured",
        EXIT_CRASH: "crash",
    }[exit_code]

    # Die nächste Handlung explizit benennen — die CLI soll nicht raten.
    if verdict == "green":
        action = ("Keine blockierenden Befunde. Nicht gemessene Checks im "
                  "Abschnitt 'unmeasured' prüfen, bevor 'geprüft' gemeldet wird.")
    elif verdict == "failed":
        action = ("Die Befunde mit severity=error beheben. Jeder Befund trägt "
                  "file, line und fix.")
    elif verdict == "unmeasured":
        action = ("NICHTS wurde gemessen — das ist kein Erfolg. Grund je Check "
                  "im Feld 'reason'.")
    else:
        action = "Mindestens ein Check ist abgestürzt. Siehe 'reason'."

    out_results = []
    emitted_sev = {"error": 0, "warning": 0, "info": 0}
    truncated_total = 0
    for r in results:
        d = r.to_dict()
        total = len(d["findings"])
        emitted = min(total, max_findings)
        truncated = total - emitted
        d["findings_total"] = total
        d["findings_emitted"] = emitted
        d["findings_truncated"] = truncated
        d["findings"] = d["findings"][:max_findings]
        truncated_total += truncated
        for finding in d["findings"]:
            emitted_sev[finding["severity"]] += 1
        out_results.append(d)

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "master_quality_gate",
        "root": ctx.root,
        "verdict": verdict,
        "exit_code": exit_code,
        "next_action": action,
        "platforms_detected": sorted(ctx.platforms()),
        "profile": ctx.config.profile_path,
        "checks": counts,
        "findings_by_severity": sev,
        "findings_emitted_by_severity": emitted_sev,
        "findings_truncated": truncated_total,
        "files_scanned": len(ctx.all_files()),
        "results": out_results,
    }


def print_text(report: dict, use_color: bool, verbose: bool) -> None:
    red, green, yellow, blue, grey, bold, reset = _color(use_color)
    v = report["verdict"]
    head = {"green": (green, "GRÜN"), "failed": (red, "DURCHGEFALLEN"),
            "unmeasured": (yellow, "NICHT GEMESSEN"), "crash": (red, "ABSTURZ")}[v]

    print(f"\n{bold}MASTER QUALITY GATE{reset}  ·  {report['root']}")
    print(f"{grey}Plattformen: {', '.join(report['platforms_detected'])}"
          f"  ·  {report['files_scanned']} Dateien"
          f"  ·  Profil: {report['profile'] or 'keins'}{reset}")
    print()

    icon = {"fail": f"{red}✗{reset}", "pass": f"{green}✓{reset}",
            "unmeasured": f"{yellow}?{reset}", "error": f"{red}!{reset}"}
    for res in report["results"]:
        st = res["status"]
        if st == "pass" and not verbose:
            continue
        line = f"{icon[st]} {bold}{res['check_id']}{reset} — {res['title']}"
        print(line)
        if st == "unmeasured":
            print(f"   {yellow}nicht gemessen:{reset} {res['reason']}")
        elif st == "error":
            print(f"   {red}{res['reason'].splitlines()[0]}{reset}")
        for f in res["findings"]:
            loc = f"{f['file']}:{f['line']}" if f.get("file") and f.get("line") \
                else (f.get("file") or "—")
            sev_col = {"error": red, "warning": yellow, "info": grey}[f["severity"]]
            print(f"   {sev_col}{f['severity'][:4].upper()}{reset} {loc}")
            print(f"        {f['message']}")
            if f.get("evidence"):
                print(f"        {grey}› {f['evidence']}{reset}")
            if f.get("fix"):
                print(f"        {blue}→ {f['fix']}{reset}")
        if res.get("findings_truncated"):
            print(f"   {grey}… und {res['findings_truncated']} weitere{reset}")
        print()

    c = report["checks"]
    s = report["findings_by_severity"]
    print("─" * 70)
    print(f"{head[0]}{bold}{head[1]}{reset}  ·  "
          f"{green}{c['pass']} bestanden{reset}, "
          f"{red}{c['fail']} durchgefallen{reset}, "
          f"{yellow}{c['unmeasured']} nicht gemessen{reset}"
          + (f", {red}{c['error']} abgestürzt{reset}" if c["error"] else ""))
    print(f"Befunde: {s['error']} Fehler · {s['warning']} Warnungen · {s['info']} Hinweise")
    print(f"{grey}{report['next_action']}{reset}")


def _agent_field(value: object) -> str:
    """Ein Agent-Feld bleibt genau eine tabgetrennte Zeile."""
    return " ".join(str(value).replace("\t", " ").splitlines())


def print_agent(report: dict) -> None:
    """Kompaktformat für eine CLI/KI: eine Zeile je Befund, stabil geparst."""
    print(f"VERDICT={report['verdict']} EXIT={report['exit_code']} "
          f"PASS={report['checks']['pass']} FAIL={report['checks']['fail']} "
          f"UNMEASURED={report['checks']['unmeasured']} "
          f"ERRORS={report['findings_by_severity']['error']} "
          f"WARNINGS={report['findings_by_severity']['warning']} "
          f"TRUNCATED={report['findings_truncated']}")
    for res in report["results"]:
        if res["status"] == "unmeasured":
            print(f"UNMEASURED\t{res['check_id']}\t{_agent_field(res['reason'])}")
        elif res["status"] == "error":
            print(f"CRASH\t{res['check_id']}\t{_agent_field(res['reason'])}")
        for f in res["findings"]:
            loc = f"{f.get('file') or '-'}:{f.get('line') or 0}"
            print(f"{f['severity'].upper()}\t{f['check_id']}\t{_agent_field(loc)}\t"
                  f"{_agent_field(f['message'])}\tFIX: {_agent_field(f.get('fix') or '-')}")
        if res["findings_truncated"]:
            print(f"TRUNCATED\t{res['check_id']}\t{res['findings_truncated']}")
    print(f"NEXT_ACTION\t{_agent_field(report['next_action'])}")


# ---------------------------------------------------------------------------
# Selbstgegenprobe
# ---------------------------------------------------------------------------

# APIs, die es nicht gibt und die trotzdem naheliegend klingen. Jeder Eintrag
# gehoert belegt (Doku/Feedback-ID), nicht vermutet.
_NONEXISTENT_APIS: list[tuple[str, str]] = [
    (".system(size:relativeTo:)",
     "SwiftUI Font.system hat kein relativeTo — nur Font.custom(_:size:relativeTo:). "
     "FB9772279 ist ein offener Feature-Request. Compiler: "
     "\"Extra argument 'relativeTo' in call\"."),
]


def run_self_test(use_color: bool) -> int:
    """Jeder Check mit Sabotage-Proben wird in BEIDE Richtungen geprüft.

    Nur kaputte Daten zu testen zeigt, dass ein Gate rot werden KANN — nicht,
    dass es bei gesunden Daten grün bleibt. Ein falsch-positives Gate ist
    schlimmer als keins.
    """
    red, green, yellow, blue, grey, bold, reset = _color(use_color)
    total = passed = 0
    failures: list[str] = []
    without_tests: list[str] = []

    required_directions = {Status.PASS, Status.FAIL}
    for check in REGISTRY.values():
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
            work = tempfile.mkdtemp(prefix="qg-selftest-")
            try:
                try:
                    for rel, content in case.files.items():
                        dest = os.path.abspath(os.path.join(work, rel))
                        if os.path.commonpath((work, dest)) != work:
                            raise ValueError(f"Testpfad verlässt Arbeitsbereich: {rel}")
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with open(dest, "w", encoding="utf-8") as fh:
                            fh.write(content)
                    ctx = Context(root=work, config=Config())
                    res = _validate_result(check, check.fn(ctx))
                    okay = res.status == case.expect
                    if okay and case.expect_finding_contains:
                        blob = " ".join(
                            (f.message or "") + " " + (f.evidence or "")
                            for f in res.findings
                        )
                        okay = case.expect_finding_contains in blob
                    if okay:
                        passed += 1
                    else:
                        got = res.status.value
                        extra = f" (reason: {res.reason})" if res.reason else ""
                        failures.append(
                            f"{check.id} / '{case.name}': erwartet {case.expect.value}, "
                            f"bekommen {got}{extra}"
                        )
                except Exception as exc:
                    failures.append(
                        f"{check.id} / '{case.name}': Probe abgestürzt: "
                        f"{type(exc).__name__}: {exc}"
                    )
            finally:
                shutil.rmtree(work, ignore_errors=True)

    # Ein fix:-Text ist Code, den jemand abschreibt. Empfiehlt er eine API,
    # die es nicht gibt, baut das Gate den Fehler ein, den es verhindern soll
    # — als Autorität, also schlimmer als gar kein Check.
    # Belegt am 18.09.2026: apple.hardcoded_font_size empfahl woertlich
    # '.system(size:relativeTo:)'. Die gibt es nicht (FB9772279 ist ein offener
    # Feature-Request); der Vorschlag brach jeden Build, der ihm folgte.
    # Gemessen wird der Kandidat (alle fix:-Texte), nicht nur der Verstoss.
    fix_texts = 0
    # Je Fall ein eigenes Verzeichnis: mehrere Faelle teilen sich oft denselben
    # Dateipfad, und der PASS-Fall wuerde den FAIL-Fall ueberschreiben — dann
    # gibt es null Findings und damit null fix-Texte zu pruefen. Das Gate waere
    # gruen, ohne etwas gemessen zu haben.
    cases = [(c, case) for c in REGISTRY.values() for case in c.self_tests]
    for check, case in cases:
        work = tempfile.mkdtemp(prefix="qg-apicheck-")
        try:
            case_valid = True
            for rel, content in case.files.items():
                dest = os.path.abspath(os.path.join(work, rel))
                if os.path.commonpath((work, dest)) != work:
                    case_valid = False
                    break
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(content)
            if not case_valid:
                continue
            try:
                res = _validate_result(
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
                for bad, why in _NONEXISTENT_APIS:
                    # Eine Erwaehnung, die das Nichtvorhandensein FESTSTELLT,
                    # ist kein Vorschlag — sonst loest die Dokumentation des
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
    print(f"{fix_texts} fix-Text(e) gegen {len(_NONEXISTENT_APIS)} bekannte "
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
    print(f"{green}{bold}BESTANDEN{reset}: {passed}/{total} Sabotage-Proben, "
          f"beide Richtungen je Check.")
    return EXIT_OK


def list_checks(use_color: bool) -> None:
    red, green, yellow, blue, grey, bold, reset = _color(use_color)
    by_platform: dict[str, list[Check]] = {}
    for c in REGISTRY.values():
        by_platform.setdefault(c.platform, []).append(c)
    print(f"\n{bold}{len(REGISTRY)} Checks{reset}\n")
    for platform in sorted(by_platform):
        print(f"{bold}{platform}{reset}")
        for c in sorted(by_platform[platform], key=lambda x: x.id):
            mark = f"{green}✓{reset}" if c.self_tests else f"{yellow}○{reset}"
            hard = " [hart ohne Profil]" if c.safe_by_default else ""
            print(f"  {mark} {c.id:<48} {c.default_severity.value}{hard}")
            print(f"     {grey}{c.title}{reset}")
            if c.guideline:
                print(f"     {grey}Quelle: {c.guideline}{reset}")
        print()
    print(f"{green}✓{reset} = mit Sabotage-Probe   {yellow}○{reset} = ohne")


# ---------------------------------------------------------------------------
# Einstieg
# ---------------------------------------------------------------------------

def _emit_runner_state(kind: str, message: str, exit_code: int,
                       args: argparse.Namespace | None = None) -> None:
    """Stabiler Maschinenbefund auch dann, wenn noch kein Report möglich ist."""
    output_format = getattr(args, "format", "text") if args else "text"
    json_target = getattr(args, "json", None) if args else None
    if output_format == "json" or json_target == "-":
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "tool": "master_quality_gate",
            "verdict": "unmeasured" if exit_code == EXIT_UNMEASURED else "crash",
            "exit_code": exit_code,
            "runner_state": {"id": kind, "message": message},
        }, ensure_ascii=False, indent=2))
    elif output_format == "agent":
        label = "RUNNER_UNMEASURED" if exit_code == EXIT_UNMEASURED else "RUNNER_ERROR"
        print(f"{label}\t{kind}\t{_agent_field(message)}")
    else:
        label = "RUNNER_UNMEASURED" if exit_code == EXIT_UNMEASURED else "RUNNER_ERROR"
        print(f"{label} [{kind}]: {message}", file=sys.stderr)


def _selector_matches(pattern: str, check_id: str) -> bool:
    return check_id == pattern or (
        pattern.endswith("*") and check_id.startswith(pattern[:-1])
    )


def main(argv: list[str]) -> int:
    ap = RunnerArgumentParser(
        prog="master_gate.py",
        description="Universelles Quality Gate über alle Guidelines.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit: 0 grün · 1 Fehler · 2 nicht gemessen · 3 Absturz",
    )
    ap.add_argument("root", nargs="?", default=os.getcwd(),
                    help="zu prüfendes Verzeichnis (Vorgabe: aktuelles)")
    ap.add_argument("--json", nargs="?", const="-", metavar="DATEI",
                    help="JSON-Report; ohne DATEI auf stdout")
    ap.add_argument("--format", choices=("text", "agent", "json"), default="text")
    ap.add_argument("--platform", help="nur diese Plattform prüfen")
    ap.add_argument("--check", action="append", default=[],
                    help="nur diese Check-ID (mehrfach, '*' als Präfix)")
    ap.add_argument("--config", help="Pfad zu einer .qualitygate.toml")
    ap.add_argument("--strict", action="store_true",
                    help="jeder FAIL bricht ab, auch ohne Profil")
    ap.add_argument("--changed-only", metavar="REF",
                    help="nur Dateien, die sich gegen REF geändert haben")
    ap.add_argument("--max-findings", type=int, default=20,
                    help="Befunde je Check (Vorgabe 20)")
    ap.add_argument("--list", action="store_true", help="Checks auflisten")
    ap.add_argument("--self-test", action="store_true",
                    help="Sabotage-Gegenprobe der Gates")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="auch bestandene Checks zeigen")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args(argv)

    use_color = not args.no_color and sys.stdout.isatty()
    if args.max_findings < 0:
        _emit_runner_state(
            "invalid_arguments", "--max-findings darf nicht negativ sein.",
            EXIT_CRASH, args,
        )
        return EXIT_CRASH

    try:
        load_checks()
    except Exception as exc:
        _emit_runner_state("plugin_load_failed", str(exc), EXIT_CRASH, args)
        return EXIT_CRASH

    known_platforms = {check.platform for check in REGISTRY.values()}
    if args.platform and args.platform not in known_platforms:
        _emit_runner_state(
            "unknown_platform", f"Unbekannte Plattform: {args.platform}",
            EXIT_CRASH, args,
        )
        return EXIT_CRASH
    unknown_checks = [
        pattern for pattern in args.check
        if not any(_selector_matches(pattern, check_id) for check_id in REGISTRY)
    ]
    if unknown_checks:
        _emit_runner_state(
            "unknown_check", "Unbekannter Check-Selektor: " + ", ".join(unknown_checks),
            EXIT_CRASH, args,
        )
        return EXIT_CRASH

    if args.list:
        list_checks(use_color)
        return EXIT_OK
    if args.self_test:
        return run_self_test(use_color)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        _emit_runner_state(
            "invalid_root", f"Kein Verzeichnis: {root}", EXIT_CRASH, args,
        )
        return EXIT_CRASH

    try:
        config = Config.load(root, args.config)
    except ConfigError as exc:
        _emit_runner_state("invalid_config", str(exc), EXIT_CRASH, args)
        return EXIT_CRASH
    if args.strict:
        config.strict = True
    ctx = Context(root=root, config=config)

    changed = None
    if args.changed_only:
        try:
            changed = ctx.changed_files(args.changed_only)
        except ChangedFilesError as exc:
            _emit_runner_state("changed_only_failed", str(exc), EXIT_CRASH, args)
            return EXIT_CRASH
        if not changed:
            _emit_runner_state(
                "changed_only_empty", "Keine geänderten Dateien im Prüfbereich.",
                EXIT_UNMEASURED, args,
            )
            return EXIT_UNMEASURED

    try:
        results = run_checks(
            ctx, only_platform=args.platform, only_checks=args.check,
            changed=changed,
        )
    except GateInputError as exc:
        _emit_runner_state("input_unreadable", str(exc), EXIT_CRASH, args)
        return EXIT_CRASH
    except Exception as exc:
        _emit_runner_state(
            "runner_crash", f"{type(exc).__name__}: {exc}", EXIT_CRASH, args,
        )
        return EXIT_CRASH

    if not results:
        _emit_runner_state(
            "zero_checks_run", "Null Checks gelaufen — das ist nicht gemessen.",
            EXIT_UNMEASURED, args,
        )
        return EXIT_UNMEASURED

    exit_code = worst_exit(results)
    if exit_code == EXIT_OK and config.strict and any(
        result.status == Status.FAIL for result in results
    ):
        exit_code = EXIT_FAILED
    # Ohne Profil sind nur die als sicher markierten Checks hart. Ein Gate, das
    # im fremden Projekt sofort rot wird über Dinge, die funktionieren, verliert
    # das Vertrauen, mit dem es durchgesetzt wird.
    if exit_code == EXIT_FAILED and not config.profile_path and not config.strict:
        safe_ids = {c.id for c in REGISTRY.values() if c.safe_by_default}
        hard = any(
            f.severity == Severity.ERROR
            for r in results if r.check_id in safe_ids
            for f in r.findings
        )
        if not hard:
            exit_code = EXIT_OK

    report = build_report(ctx, results, exit_code, args.max_findings)

    if args.format == "json" or args.json == "-":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.format == "agent":
        print_agent(report)
    else:
        print_text(report, use_color, args.verbose)

    if args.json and args.json != "-":
        try:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            print(f"JSON-Report nicht schreibbar: {exc}", file=sys.stderr)
            return EXIT_CRASH

    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(EXIT_CRASH)
