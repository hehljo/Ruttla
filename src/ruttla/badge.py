"""Öffentliche Projektkarte: Badge, Verlauf und Übersicht aus echten Vollscans.

Gegenstück zur lokalen Statistik (`stats.py`): die bleibt auf dem Rechner, die
Karte ist zum Veröffentlichen gedacht — typischerweise schreibt sie ein CI-Lauf
auf einen eigenen Branch. Deshalb steht hier nur, was ohnehin jeder nachmessen
kann: Zählwerte eines Scans, Regel-IDs, Ruttla-Version, Commit und Lauf-URL.
Nie: Pfade, Evidenz, Meldungen, Quelltext, das Prüfwurzelverzeichnis.

Nachprüfbarkeit statt Behauptung: jede Verlaufszeile nennt Commit und
Ruttla-Version; derselbe Scan an diesem Commit mit dieser Version liefert
dieselben Zahlen. Der Verlauf beginnt beim ersten erfassten Scan — nichts wird
nachgetragen oder hochgerechnet.

`update` scannt selbst und immer vollständig: ein `--changed-only`-Lauf sähe im
JSON-Report gleich aus und würde „weniger Befunde“ vortäuschen.

Veränderungen zählen nur zwischen vergleichbaren Scans (beide gemessen, gleiche
Ruttla-Version, gleicher Regelsatz). Ein Rückgang heißt „Befunde weniger“, nicht
„behoben“ — die Karte sieht nicht, warum ein Befund verschwand.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

CARD_SCHEMA = "ruttla-card/1"
EXIT_OK = 0
EXIT_CRASH = 3  # wie engine.EXIT_CRASH
HISTORY = "history.jsonl"
STATUS = "status.json"
SUMMARY = "README.md"  # GitHub zeigt es beim Öffnen des Branches/Ordners an
BADGES = ("badge.json", "badge-history.json")
# Nur gemessene Scans gehen in Verlauf und Vergleich ein (0 grün, 1 Befunde).
MEASURED_EXITS = (0, 1)
SPARK = "▁▂▃▄▅▆▇█"
SPARK_RUNS = 30
TOP_RULES = 10
# Projektnamen (owner/repo) sind frei, aber eine Zeile ohne Steuerzeichen.
MAX_NAME = 100


class CardError(RuntimeError):
    """Karte nicht lesbar oder nicht schreibbar — Exit 3, nie still."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_name(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or len(value) > MAX_NAME or any(ord(c) < 32 for c in value):
        raise CardError(f"ungültiger Projektname: {value!r}")
    return value


def entry_from_report(report: dict, *, commit: str | None = None,
                      run_url: str | None = None, recorded_at: str | None = None,
                      ci: bool = False) -> dict:
    """Eine Verlaufszeile aus einem JSON-Report — nur Zählwerte und Regel-IDs."""
    if not isinstance(report, dict) or report.get("tool_name") != "ruttla":
        raise CardError("kein Ruttla-JSON-Report")
    if not str(report.get("schema_version", "")).startswith("1."):
        raise CardError(f"Report-Schema {report.get('schema_version')!r} unbekannt")
    results = report.get("results")
    if not isinstance(results, list):
        raise CardError("Report ohne results")
    ran = sorted(r["check_id"] for r in results)
    by_check = {r["check_id"]: int(r.get("findings_total") or 0)
                for r in results if r.get("findings_total")}
    sev = report.get("findings_by_severity") or {}
    return {
        "schema": CARD_SCHEMA,
        "recorded_at": recorded_at or _now(),
        "commit": commit,
        "run_url": run_url,
        "ci": bool(ci),
        "ruttla_version": report.get("tool_version"),
        "report_schema": report.get("schema_version"),
        "exit_code": int(report.get("exit_code")),
        "verdict": report.get("verdict"),
        "rules_run": len(ran),
        "rules_digest": hashlib.sha256("\n".join(ran).encode()).hexdigest()[:16],
        "checks": {k: int((report.get("checks") or {}).get(k, 0))
                   for k in ("pass", "fail", "unmeasured", "error")},
        "files_scanned": int(report.get("files_scanned") or 0),
        "platforms": sorted(p for p in report.get("platforms_detected", [])
                            if p != "universal"),
        "blocking": int(report.get("blocking_findings") or 0),
        "advisory": int(report.get("advisory_findings") or 0),
        "by_severity": {k: int(sev.get(k, 0)) for k in ("error", "warning", "info")},
        "by_check": dict(sorted(by_check.items())),
    }


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    history = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CardError(f"{path.name}:{number}: kein JSON ({exc.msg})") from exc
        if not isinstance(entry, dict) or entry.get("schema") != CARD_SCHEMA:
            raise CardError(f"{path.name}:{number}: Schema {entry.get('schema') if isinstance(entry, dict) else None!r} unbekannt")
        history.append(entry)
    return history


def _same_scan(a: dict, b: dict) -> bool:
    keys = ("ruttla_version", "rules_digest", "exit_code", "blocking", "advisory", "by_check")
    return all(a.get(k) == b.get(k) for k in keys)


def append(history: list[dict], entry: dict) -> bool:
    """Hängt an; ein erneuter Lauf auf demselben Commit mit gleichem Ergebnis zählt nicht."""
    if entry["exit_code"] not in MEASURED_EXITS:
        return False
    last = history[-1] if history else None
    if last and entry.get("commit") and last.get("commit") == entry["commit"] \
            and _same_scan(last, entry):
        return False
    history.append(entry)
    return True


def comparable(a: dict, b: dict) -> bool:
    return (a["exit_code"] in MEASURED_EXITS and b["exit_code"] in MEASURED_EXITS
            and a.get("ruttla_version") == b.get("ruttla_version")
            and a.get("rules_digest") == b.get("rules_digest"))


def totals(history: list[dict]) -> dict:
    """Kennzahlen über den ganzen Verlauf — nur aus erfassten Zeilen."""
    down = up = not_comparable = 0
    per_rule_down: dict[str, int] = {}
    for prev, cur in zip(history, history[1:]):
        if not comparable(prev, cur):
            not_comparable += 1
            continue
        for rule in set(prev["by_check"]) | set(cur["by_check"]):
            delta = cur["by_check"].get(rule, 0) - prev["by_check"].get(rule, 0)
            if delta < 0:
                down -= delta
                per_rule_down[rule] = per_rule_down.get(rule, 0) - delta
            elif delta > 0:
                up += delta
    streak = 0
    for entry in reversed(history):
        if entry["blocking"]:
            break
        streak += 1
    first = history[0] if history else None
    last = history[-1] if history else None
    return {
        "scans": len(history),
        "scans_ci": sum(1 for e in history if e.get("ci")),
        "first_recorded": first["recorded_at"] if first else None,
        "last_recorded": last["recorded_at"] if last else None,
        "findings_first": (first["blocking"] + first["advisory"]) if first else None,
        "findings_now": (last["blocking"] + last["advisory"]) if last else None,
        "blocking_first": first["blocking"] if first else None,
        "blocking_now": last["blocking"] if last else None,
        "findings_down": down,
        "findings_up": up,
        "transitions_not_comparable": not_comparable,
        "blocking_free_streak": streak,
        "rules_with_fewer_findings": dict(
            sorted(per_rule_down.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def _badge(label: str, message: str, color: str) -> dict:
    # shields.io-Endpoint-Format: https://shields.io/badges/endpoint-badge
    return {"schemaVersion": 1, "label": label, "message": message, "color": color}


def badges(history: list[dict], unmeasured: bool = False) -> dict[str, dict]:
    if not history:
        return {BADGES[0]: _badge("ruttla", "not measured", "lightgrey"),
                BADGES[1]: _badge("ruttla history", "no scans yet", "lightgrey")}
    last = history[-1]
    if unmeasured:
        # Der jüngste Scan hat nichts gemessen: nie den alten grünen Stand zeigen.
        current = _badge("ruttla", "not measured", "lightgrey")
    elif last["blocking"]:
        current = _badge("ruttla", f"{last['blocking']} blocking · {last['rules_run']} rules", "red")
    else:
        current = _badge("ruttla", f"0 blocking · {last['rules_run']} rules", "brightgreen")
    t = totals(history)
    since = (t["first_recorded"] or "")[:10]
    word = "scan" if t["scans"] == 1 else "scans"
    hist = _badge("ruttla history", f"{t['scans']} {word} since {since}", "blue")
    return {BADGES[0]: current, BADGES[1]: hist}


def sparkline(values: list[int]) -> str:
    if not values:
        return ""
    low, high = min(values), max(values)
    if high == low:
        return SPARK[0] * len(values)
    span = high - low
    return "".join(SPARK[round((v - low) * (len(SPARK) - 1) / span)] for v in values)


_MD_SPECIAL = re.compile(r"([\\`*_\[\]()|!#~{}])")


def _md(value) -> str:
    """Fremder Text als reiner Text: kein Link, Bild, HTML oder Zellbruch.

    `combine` liest status.json aus fremden Repos — ein Projektname wie
    `[x](https://…)` oder `<img src=…>` darf in der Sammelkarte nichts auslösen.
    """
    text = "".join(" " if ord(c) < 32 else c for c in str(value))
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _MD_SPECIAL.sub(r"\\\1", text)


def _code(value) -> str:
    """Inhalt für `…`: Backticks und Umbrüche raus, Pipe bleibt in der Tabellenzelle."""
    text = "".join(" " if ord(c) < 32 else c for c in str(value)).replace("`", "'")
    return text.replace("|", "\\|")


def _n(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CardError(f"Zählwert erwartet, gefunden: {value!r}")
    return value


def _cell(value) -> str:
    return "—" if value is None else _md(value)


def render_summary(history: list[dict], project: str | None,
                   badge_base: str | None = None) -> str:
    t = totals(history)
    title = f"Ruttla quality record — {_md(project)}" if project else "Ruttla quality record"
    lines = [f"# {title}", ""]
    if badge_base:
        for name in BADGES:
            url = f"https://img.shields.io/endpoint?url={badge_base.rstrip('/')}/{name}"
            lines.append(f"![{name.removesuffix('.json')}]({url})")
        lines.append("")
    if not history:
        lines += ["No measured scan recorded yet.", ""]
        return "\n".join(lines)
    last = history[-1]
    lines += [
        "Generated by `ruttla badge update` from full scans. Every row in "
        f"`{HISTORY}` names the commit and the Ruttla version — re-running that "
        "version on that commit reproduces the counts.",
        "",
        "## Now",
        "",
        "| | |",
        "|---|---|",
        f"| Blocking findings | **{last['blocking']}** |",
        f"| Advisory findings | {last['advisory']} |",
        f"| Rules run | {last['rules_run']} (pass {last['checks']['pass']} · "
        f"fail {last['checks']['fail']} · not measured {last['checks']['unmeasured']}) |",
        f"| Files scanned | {last['files_scanned']} |",
        f"| Platforms | {', '.join(_md(p) for p in last['platforms']) or '—'} |",
        f"| Ruttla | {_cell(last['ruttla_version'])} |",
        f"| Commit | {_cell(last.get('commit'))} |",
        f"| Recorded | {_cell(last['recorded_at'])} |",
        "",
        "## History",
        "",
        "| | |",
        "|---|---|",
        f"| Recorded scans | {t['scans']} ({t['scans_ci']} on CI) |",
        f"| Since | {_cell(t['first_recorded'])} |",
        f"| Findings first → now | {t['findings_first']} → {t['findings_now']} |",
        f"| Blocking first → now | {t['blocking_first']} → {t['blocking_now']} |",
        f"| Findings fewer / more (comparable scans) | {t['findings_down']} / {t['findings_up']} |",
        f"| Scans without blocking findings in a row | {t['blocking_free_streak']} |",
        f"| Steps not comparable (Ruttla or rule set changed) | {t['transitions_not_comparable']} |",
        "",
    ]
    recent = history[-SPARK_RUNS:]
    lines += [
        f"Findings over the last {len(recent)} scans: "
        f"`{sparkline([e['blocking'] + e['advisory'] for e in recent])}`",
        "",
    ]
    if t["rules_with_fewer_findings"]:
        lines += ["## Rules with fewer findings", "", "| Rule | Fewer |", "|---|---:|"]
        for rule, count in list(t["rules_with_fewer_findings"].items())[:TOP_RULES]:
            lines.append(f"| `{_code(rule)}` | {_n(count)} |")
        lines.append("")
    lines += [
        "## What these numbers do not say",
        "",
        "- History starts at the first recorded scan; nothing before it is estimated.",
        "- *Fewer findings* is not *fixed*: a finding can also disappear because code was removed.",
        "- Counts compare only between scans with the same Ruttla version and rule set.",
        "- These are scan results of one project, not adoption by other people.",
        "",
    ]
    return "\n".join(lines)


def status(history: list[dict], project: str | None) -> dict:
    return {"schema": CARD_SCHEMA, "project": project,
            "latest": history[-1] if history else None, "totals": totals(history)}


def _write(path: Path, text: str) -> None:
    # Atomar: ein abgebrochener Lauf hinterlässt nie eine halbe Karte. LF fest,
    # damit derselbe Verlauf auf Windows dieselben Bytes hat.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_card(out: Path, history: list[dict], project: str | None,
               badge_base: str | None, unmeasured: bool = False) -> None:
    _write(out / HISTORY, "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n"
                                  for e in history))
    _write(out / STATUS, json.dumps(status(history, project), indent=2,
                                    ensure_ascii=False, sort_keys=True) + "\n")
    for name, data in badges(history, unmeasured).items():
        _write(out / name, json.dumps(data, sort_keys=True) + "\n")
    _write(out / SUMMARY, render_summary(history, project, badge_base))


def scan(root: Path) -> dict:
    """Vollscan über die echte CLI; Ausgabe verworfen, Report aus der JSON-Datei."""
    from . import cli

    with tempfile.TemporaryDirectory(prefix="ruttla-badge-") as tmp:
        target = Path(tmp) / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main([str(root), "--no-color", "--json", str(target)])
        if code == EXIT_CRASH or not target.exists():
            raise CardError(f"Scan von {root} lieferte keinen Report (Exit {code})")
        return json.loads(target.read_text(encoding="utf-8"))


def combine(dirs: list[Path]) -> list[dict]:
    """status.json mehrerer Karten lesen — für eine Übersicht über Projekte."""
    cards = []
    for directory in dirs:
        path = directory / STATUS
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CardError(f"{path}: {exc}") from exc
        if data.get("schema") != CARD_SCHEMA:
            raise CardError(f"{path}: Schema {data.get('schema')!r} unbekannt")
        cards.append(data)
    return cards


def render_combined(cards: list[dict]) -> str:
    measured = [c for c in cards if c.get("latest")]
    scans = sum(_n(c["totals"]["scans"]) for c in cards)
    lines = [
        "# Ruttla across projects", "",
        f"{len(cards)} projects · {scans} recorded scans · "
        f"{sum(_n(c['latest']['blocking']) for c in measured)} blocking findings now", "",
        "| Project | Blocking | Advisory | Rules | Scans | Since | Fewer / more |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for c in sorted(cards, key=lambda c: str(c.get("project") or "")):
        t, last = c["totals"], c.get("latest")
        name = _md(c["project"]) if c.get("project") else "—"
        if not last:
            lines.append(f"| {name} | — | — | — | 0 | — | — |")
            continue
        lines.append(
            f"| {name} | {_n(last['blocking'])} | {_n(last['advisory'])} | "
            f"{_n(last['rules_run'])} | {_n(t['scans'])} | "
            f"{_md(str(t['first_recorded'] or '')[:10])} | "
            f"{_n(t['findings_down'])} / {_n(t['findings_up'])} |")
    lines += ["", "Each project links its own `history.jsonl`; this table only adds them up.", ""]
    return "\n".join(lines)


def _parser(prog: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=f"{prog} badge",
        description="Öffentliche Projektkarte: Badge, Verlauf und Übersicht aus Vollscans "
                    "(zum Veröffentlichen, z. B. per CI auf einen eigenen Branch).",
        epilog="Exit: 0 Karte geschrieben (auch bei Befunden) · 3 Scan/Karte fehlerhaft")
    sub = ap.add_subparsers(dest="action", required=True)
    p = sub.add_parser("update", help="Vollscan, Verlauf anhängen, Karte neu schreiben")
    p.add_argument("root", nargs="?", default=".", help="Projektwurzel (Vorgabe .)")
    p.add_argument("--dir", required=True, help="Kartenverzeichnis (Verlauf liegt dort)")
    p.add_argument("--project", help="Anzeigename, z. B. owner/repo")
    p.add_argument("--commit", help="Commit des Scans (CI: $GITHUB_SHA)")
    p.add_argument("--run-url", help="Link zum Lauf, der die Zahlen belegt")
    p.add_argument("--badge-base", help="öffentliche Basis-URL des Kartenverzeichnisses "
                                        "(für die Badges in der Übersicht)")
    p = sub.add_parser("combine", help="Übersicht über mehrere Kartenverzeichnisse")
    p.add_argument("dirs", nargs="+", help="Kartenverzeichnisse mit status.json")
    p.add_argument("--out", required=True, help="Zieldatei (Markdown)")
    return ap


def run_badge_command(argv: list[str], prog: str = "ruttla") -> int:
    ap = _parser(prog)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_CRASH
    try:
        if args.action == "combine":
            cards = combine([Path(d) for d in args.dirs])
            _write(Path(args.out), render_combined(cards))
            print(f"ruttla badge: {len(cards)} Karten → {args.out}")
            return EXIT_OK
        out = Path(args.dir)
        project = _clean_name(args.project)
        history = load_history(out / HISTORY)  # vor dem Scan: kaputter Verlauf bricht früh ab
        report = scan(Path(args.root))
        entry = entry_from_report(report, commit=args.commit, run_url=args.run_url,
                                  ci=bool(os.environ.get("CI")))
        added = append(history, entry)
        write_card(out, history, project, args.badge_base,
                   unmeasured=entry["exit_code"] not in MEASURED_EXITS)
        if entry["exit_code"] not in MEASURED_EXITS:
            note = "nicht gemessen — nicht in den Verlauf übernommen"
        else:
            note = "angehängt" if added else "gleicher Commit, gleiches Ergebnis — nicht doppelt gezählt"
        print(f"ruttla badge: {entry['blocking']} blockierend · {entry['rules_run']} Regeln · "
              f"{note} → {out}")
        return EXIT_OK
    except (CardError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ruttla badge: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_CRASH
