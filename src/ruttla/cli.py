"""Command-line adapter: argument parsing, reporter selection, exit codes.

    ruttla [ROOT] [options]          (also: python -m ruttla, python3 master_gate.py)

Exit codes — the contract with the calling CLI or CI (docs/CONTRACTS.md):
    0  measured, no blocking finding (advisory findings may exist)
    1  at least one blocking finding
    2  nothing meaningful was measured — NOT a success
    3  runner crash, invalid input, config or plugin error

'Nicht gemessen' ist ein eigener Ausgang, nie stillschweigend grün.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .catalog import catalog_json, explain, rules_markdown
from .config import Config
from .context import Context
from .engine import (  # noqa: F401  (re-exported for the legacy master_gate API)
    EXIT_CRASH,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    PluginLoadError,
    _crashed_check,
    _validate_result,
    apply_exit_policy,
    load_checks,
    run_checks,
    selector_matches,
    worst_exit,
)
from .models import SCHEMA_VERSION, ChangedFilesError, ConfigError, GateInputError  # noqa: F401
from .platforms import PACK_PLATFORMS, PLATFORMS_WITHOUT_PACK
from .registry import REGISTRY, Check
from .reporting import (
    build_report,
    build_sarif,
    dumps_report,
    print_agent,
    print_text,
    runner_state_report,
)
from .reporting.agent import agent_field as _agent_field
from .reporting.text import palette as _color
from .selftest import NONEXISTENT_APIS as _NONEXISTENT_APIS  # noqa: F401
from .selftest import run_self_test

FORMATS = ("text", "agent", "json", "sarif", "markdown")


class RunnerArgumentParser(argparse.ArgumentParser):
    """Argparse-Fehler gehören laut Runner-Vertrag zu Exit 3, nicht Exit 2."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_CRASH, f"RUNNER_ERROR\tinvalid_arguments\t{message}\n")


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


def _emit_runner_state(kind: str, message: str, exit_code: int,
                       args: argparse.Namespace | None = None) -> None:
    """Stabiler Maschinenbefund auch dann, wenn noch kein Report möglich ist."""
    output_format = getattr(args, "format", "text") if args else "text"
    json_target = getattr(args, "json", None) if args else None
    if output_format in ("json", "sarif") or json_target == "-":
        print(json.dumps(runner_state_report(kind, message, exit_code),
                         ensure_ascii=False, indent=2))
    elif output_format == "agent":
        label = "RUNNER_UNMEASURED" if exit_code == EXIT_UNMEASURED else "RUNNER_ERROR"
        print(f"{label}\t{kind}\t{_agent_field(message)}")
    else:
        label = "RUNNER_UNMEASURED" if exit_code == EXIT_UNMEASURED else "RUNNER_ERROR"
        print(f"{label} [{kind}]: {message}", file=sys.stderr)


_selector_matches = selector_matches


def build_parser(prog: str = "ruttla") -> RunnerArgumentParser:
    ap = RunnerArgumentParser(
        prog=prog,
        description="Ruttla — lokales, deterministisches Quality Gate. "
                    "Kein LLM, kein Netz, Zielcode wird nie ausgeführt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit: 0 grün · 1 blockierende Befunde · 2 nicht gemessen · 3 Absturz/Fehlbedienung",
    )
    ap.add_argument("root", nargs="?", default=None,
                    help="zu prüfendes Verzeichnis (Vorgabe: aktuelles)")
    ap.add_argument("--version", action="store_true", help="Version ausgeben")
    ap.add_argument("--json", nargs="?", const="-", metavar="DATEI",
                    help="JSON-Report; ohne DATEI auf stdout")
    ap.add_argument("--sarif", metavar="DATEI",
                    help="SARIF-2.1.0-Report zusätzlich in DATEI schreiben")
    ap.add_argument("--format", choices=FORMATS, default="text",
                    help="Ausgabeformat (bei --list: text, json oder markdown)")
    ap.add_argument("--platform", help="nur dieses Regelpaket prüfen")
    ap.add_argument("--check", action="append", default=[],
                    help="nur diese Check-ID (mehrfach, '*' als Präfix)")
    ap.add_argument("--config", help="Pfad zu einem Profil (.ruttla.toml)")
    ap.add_argument("--strict", action="store_true",
                    help="jeder FAIL blockiert, auch ohne Profil")
    ap.add_argument("--changed-only", metavar="REF",
                    help="nur Dateien, die sich gegen REF geändert haben")
    ap.add_argument("--max-findings", type=int, default=20,
                    help="Befunde je Check (Vorgabe 20)")
    ap.add_argument("--list", action="store_true", help="Checks auflisten")
    ap.add_argument("--explain", metavar="CHECK_ID",
                    help="Begründung, Referenzen und Proben eines Checks zeigen")
    ap.add_argument("--self-test", action="store_true",
                    help="Sabotage-Gegenprobe der Gates")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="auch bestandene Checks zeigen")
    ap.add_argument("--no-color", action="store_true")
    return ap


def main(argv: list[str] | None = None, prog: str = "ruttla") -> int:
    args = build_parser(prog).parse_args(sys.argv[1:] if argv is None else argv)

    if args.version:
        print(f"ruttla {__version__} (report schema {SCHEMA_VERSION})")
        return EXIT_OK

    use_color = not args.no_color and sys.stdout.isatty()
    if args.format == "markdown" and not args.list:
        _emit_runner_state(
            "invalid_arguments", "--format markdown gibt es nur zusammen mit --list.",
            EXIT_CRASH, args,
        )
        return EXIT_CRASH
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

    if args.platform and args.platform not in PACK_PLATFORMS:
        detail = (" — erkannt, aber noch ohne Regelpaket"
                  if args.platform in PLATFORMS_WITHOUT_PACK else "")
        _emit_runner_state(
            "unknown_platform", f"Unbekannte Plattform: {args.platform}{detail}",
            EXIT_CRASH, args,
        )
        return EXIT_CRASH
    unknown_checks = [
        pattern for pattern in args.check
        if not any(selector_matches(pattern, check_id) for check_id in REGISTRY)
    ]
    if unknown_checks:
        _emit_runner_state(
            "unknown_check", "Unbekannter Check-Selektor: " + ", ".join(unknown_checks),
            EXIT_CRASH, args,
        )
        return EXIT_CRASH

    if args.explain:
        if args.explain not in REGISTRY:
            _emit_runner_state("unknown_check", f"Unbekannte Check-ID: {args.explain}",
                               EXIT_CRASH, args)
            return EXIT_CRASH
        print(explain(args.explain), end="")
        return EXIT_OK
    if args.list:
        if args.format == "json":
            print(catalog_json())
        elif args.format == "markdown":
            print(rules_markdown(), end="")
        else:
            list_checks(use_color)
        return EXIT_OK
    if args.self_test:
        return run_self_test(use_color)

    root = os.path.abspath(args.root if args.root is not None else os.getcwd())
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

    # Ohne Profil sind nur die als sicher markierten Checks hart. Ein Gate, das
    # im fremden Projekt sofort rot wird über Dinge, die funktionieren, verliert
    # das Vertrauen, mit dem es durchgesetzt wird.
    exit_code = apply_exit_policy(results, config)
    report = build_report(ctx, results, exit_code, args.max_findings)

    def sarif_doc() -> dict:
        rules = {cid: REGISTRY[cid].metadata() for cid in
                 (r["check_id"] for r in report["results"]) if cid in REGISTRY}
        return build_sarif(report, rules, [f.rel for f in ctx.all_files()])

    if args.format == "json" or args.json == "-":
        print(dumps_report(report))
    elif args.format == "sarif":
        print(json.dumps(sarif_doc(), ensure_ascii=False, indent=2))
    elif args.format == "agent":
        print_agent(report)
    else:
        print_text(report, use_color, args.verbose)

    targets = []
    if args.json and args.json != "-":
        targets.append((args.json, report))
    if args.sarif:
        targets.append((args.sarif, sarif_doc()))
    for path, document in targets:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(document, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            print(f"Report nicht schreibbar: {exc}", file=sys.stderr)
            return EXIT_CRASH

    return exit_code


def _utf8_streams() -> None:
    """Machine output is UTF-8 on every OS (docs/CONTRACTS.md).

    Windows pipes default to the ANSI code page; the reports contain ✓/✗,
    umlauts and file names that cp1252 cannot encode.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def run(argv: list[str] | None = None, prog: str = "ruttla") -> int:
    """``main`` plus process-level edge cases shared by every entry point."""
    _utf8_streams()
    try:
        return main(argv, prog=prog)
    except KeyboardInterrupt:
        return EXIT_CRASH
    except BrokenPipeError:
        # The reader closed stdout early (``ruttla | head``): the report was
        # not delivered, which is an output error — never a finding (1) and
        # never green (0). Silence the interpreter's second flush attempt.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return EXIT_CRASH


def entry() -> None:
    """Console-script entry point (``ruttla``)."""
    sys.exit(run())
