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
    REGISTRY, Check, CheckResult, Config, Context, Finding, Severity, Status,
    SCHEMA_VERSION,
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


def load_checks() -> None:
    """Lädt jedes Modul im checks/-Verzeichnis. Iteriert über das Verzeichnis,
    statt eine Liste zu pflegen — eine gepflegte Liste ist die zweite Liste."""
    checks_dir = os.path.join(HERE, "checks")
    if not os.path.isdir(checks_dir):
        raise RuntimeError(f"Check-Verzeichnis fehlt: {checks_dir}")
    loaded = 0
    for name in sorted(os.listdir(checks_dir)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        path = os.path.join(checks_dir, name)
        spec = importlib.util.spec_from_file_location(f"qg_checks_{name[:-3]}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        loaded += 1
    if loaded == 0:
        # "Null Gates gefunden" ist rot, nicht grün.
        raise RuntimeError("Null Check-Module geladen — der Runner prüft nichts.")


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------

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
        severity = ctx.config.severity_for(check.id, check.default_severity)
        if severity is None:
            continue  # im Profil abgeschaltet
        try:
            res = check.fn(ctx)
        except Exception:
            res = CheckResult(
                check.id, Status.ERROR, check.title,
                reason="Check abgestürzt:\n" + traceback.format_exc(limit=4),
                platform=check.platform,
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
    for r in results:
        d = r.to_dict()
        if len(d["findings"]) > max_findings:
            d["findings_truncated"] = len(d["findings"]) - max_findings
            d["findings"] = d["findings"][:max_findings]
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


def print_agent(report: dict) -> None:
    """Kompaktformat für eine CLI/KI: eine Zeile je Befund, stabil geparst."""
    print(f"VERDICT={report['verdict']} EXIT={report['exit_code']} "
          f"PASS={report['checks']['pass']} FAIL={report['checks']['fail']} "
          f"UNMEASURED={report['checks']['unmeasured']} "
          f"ERRORS={report['findings_by_severity']['error']} "
          f"WARNINGS={report['findings_by_severity']['warning']}")
    for res in report["results"]:
        if res["status"] == "unmeasured":
            print(f"UNMEASURED\t{res['check_id']}\t{res['reason']}")
        elif res["status"] == "error":
            print(f"CRASH\t{res['check_id']}\t{res['reason'].splitlines()[0]}")
        for f in res["findings"]:
            loc = f"{f.get('file') or '-'}:{f.get('line') or 0}"
            print(f"{f['severity'].upper()}\t{f['check_id']}\t{loc}\t"
                  f"{f['message']}\tFIX: {f.get('fix') or '-'}")
    print(f"NEXT_ACTION\t{report['next_action']}")


# ---------------------------------------------------------------------------
# Selbstgegenprobe
# ---------------------------------------------------------------------------

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

    for check in REGISTRY.values():
        if not check.self_tests:
            without_tests.append(check.id)
            continue
        directions = {c.expect for c in check.self_tests}
        if len(directions) < 2:
            failures.append(
                f"{check.id}: nur eine Richtung geprüft ({directions}) — "
                "die Gegenprobe braucht BEIDE."
            )
        for case in check.self_tests:
            total += 1
            work = tempfile.mkdtemp(prefix="qg-selftest-")
            try:
                for rel, content in case.files.items():
                    dest = os.path.join(work, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "w", encoding="utf-8") as fh:
                        fh.write(content)
                ctx = Context(root=work, config=Config())
                res = check.fn(ctx)
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
            finally:
                shutil.rmtree(work, ignore_errors=True)

    print(f"\n{bold}SABOTAGE-GEGENPROBE DER GATES{reset}\n")
    print(f"{len(REGISTRY)} Checks registriert, "
          f"{len(REGISTRY) - len(without_tests)} mit Sabotage-Proben.\n")
    for f in failures:
        print(f"  {red}✗{reset} {f}")
    if without_tests:
        print(f"\n{yellow}Ohne Sabotage-Probe ({len(without_tests)}):{reset}")
        for cid in without_tests:
            print(f"  {grey}· {cid}{reset}")
        print(f"{grey}  Ein Gate, das nie rot war, prüft nichts. Diese Checks "
              f"sind ungeprüfte Zusagen.{reset}")

    print("\n" + "─" * 70)
    if total == 0:
        print(f"{red}NICHT GEMESSEN: null Sabotage-Proben gelaufen.{reset}")
        return EXIT_UNMEASURED
    if failures:
        print(f"{red}{bold}DURCHGEFALLEN{reset}: {passed}/{total} Proben bestanden, "
              f"{len(failures)} Problem(e).")
        return EXIT_FAILED
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

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
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

    try:
        load_checks()
    except Exception as exc:
        print(f"Gate konnte nicht starten: {exc}", file=sys.stderr)
        return EXIT_CRASH

    if args.list:
        list_checks(use_color)
        return EXIT_OK
    if args.self_test:
        return run_self_test(use_color)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"Kein Verzeichnis: {root}", file=sys.stderr)
        return EXIT_CRASH

    config = Config.load(root, args.config)
    if args.strict:
        config.strict = True
    ctx = Context(root=root, config=config)

    changed = None
    if args.changed_only:
        changed = ctx.changed_files(args.changed_only)
        if changed is None:
            print(f"Konnte geänderte Dateien gegen '{args.changed_only}' nicht "
                  f"ermitteln — kein Git-Repo oder ungültige Referenz.",
                  file=sys.stderr)
            return EXIT_CRASH

    try:
        results = run_checks(
            ctx, only_platform=args.platform, only_checks=args.check,
            changed=changed,
        )
    except Exception:
        traceback.print_exc()
        return EXIT_CRASH

    if not results:
        print("Null Checks gelaufen — das ist nicht gemessen, nicht grün.",
              file=sys.stderr)
        return EXIT_UNMEASURED

    exit_code = worst_exit(results)
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
