"""`ruttla triage`: Befunde aus JSON-Reports in Fix-Aufträge je Repo und Fix-Klasse.

Jeder Auftrag nennt die erlaubten Dateien, die Fundstellen, die Abnahme als
Befehle mit Exit-Code und die Grenzen (keine Policy, kein Push). Die Abnahme
prüft ein Skript, nicht der Agent: `ruttla guard` gegen die Basis und der Scan
mit `--trusted-ref` auf genau diese Checks.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

CLASSES = ("mechanical", "catalog", "judgement", "security")
WORKER = {
    "mechanical": "Flash 3.8 oder Haiku (mechanisch, Aufrufbudget 60)",
    "catalog": "Haiku mit vorab geklärter Build-/Modulkette, sonst SOL",
    "judgement": "SOL 6.1 high",
    "security": "SOL 6.1 high oder Claude — Ergebnis immer von Claude prüfen lassen",
}
_TABLE = Path(__file__).with_name("fix_classes.toml")
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def load_table(path: Path = _TABLE) -> dict:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "ruttla-fix-classes/1":
        raise ValueError(f"{path}: unbekanntes Schema")
    for value in [data.get("default"), *data.get("prefix", {}).values(),
                  *data.get("check", {}).values()]:
        if value not in CLASSES:
            raise ValueError(f"{path}: unbekannte Fix-Klasse {value!r}")
    return data


def classify(check_id: str, table: dict) -> str:
    if check_id in table.get("check", {}):
        return table["check"][check_id]
    return table.get("prefix", {}).get(check_id.split(".", 1)[0], table["default"])


def _head(root: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def tasks_from_report(report: dict, table: dict) -> list[dict]:
    root = report.get("root")
    if not root or "results" not in report:
        raise ValueError("kein Ruttla-JSON-Report (root/results fehlen)")
    grouped: dict[str, dict] = {}
    for result in report["results"]:
        findings = list(result.get("findings", []))
        total = result.get("findings_total", len(findings))
        if not total:
            continue
        cls = classify(result["check_id"], table)
        task = grouped.setdefault(cls, {"class": cls, "root": root, "checks": {},
                                        "files": set(), "blocking": 0})
        task["checks"][result["check_id"]] = {
            "total": total, "listed": findings,
            "truncated": result.get("findings_truncated", 0)}
        task["files"].update(f["file"] for f in findings if f.get("file"))
        task["blocking"] += sum(1 for f in findings if f.get("blocking"))
    return [grouped[c] for c in CLASSES if c in grouped]


def render_task(task: dict, base: str) -> str:
    root, ids = task["root"], sorted(task["checks"])
    check_args = " ".join(f"--check {i}" for i in ids)
    lines = [
        f"# Fix-Auftrag: {Path(root).name} · {task['class']}", "",
        f"Bearbeiter: {WORKER[task['class']]}", f"Repo: `{root}` · Basis: `{base}`", "",
        "## Ziel", "",
        "Die unten genannten Befunde **an der Ursache** beheben. Jeder Befund nennt "
        "Datei, Zeile und den Fix-Vorschlag des Checks (`ruttla --explain ID` erklärt die Regel).",
        "", "## Grenzen", "",
        "- In einem eigenen `git worktree` auf eigenem Branch arbeiten, nie auf main.",
        "- Nur die gelisteten Dateien ändern; Tests dazu dürfen ergänzt, nie entfernt werden.",
        "- Tabu: `.ruttla.toml`, `.ruttla/` (auch Ausnahmen), `.github/`, `.gitignore`, "
        "Unterdrückungs-Kommentare (`noqa`, `eslint-disable`, `@ts-ignore` …).",
        "- Hält ein Befund für einen Fehlalarm: nicht umgehen, im Bericht begründen.",
        "- Kein Commit, kein Push, kein Deploy. Höchstens eine Korrekturrunde, dann Bericht.",
        "", "## Abnahme (alle drei Exit 0, ohne Pipe ausführen)", "", "```",
        f"ruttla guard {root} --base {base}",
        f"ruttla {root} --trusted-ref {base} {check_args} --strict --format agent",
        "# plus die Projekttests laut AGENTS.md/README des Repos", "```", "",
        "Bericht als Datei, Antwort nur der Pfad: was geändert, welche Befunde offen und warum.",
        "", "## Befunde", "",
    ]
    for check_id in ids:
        info = task["checks"][check_id]
        lines.append(f"### `{check_id}` — {info['total']} Fundstellen")
        if info["truncated"]:
            lines.append(f"(Report gekürzt: {info['truncated']} weitere nicht gelistet — "
                         "die Abnahme zählt alle; vollständig mit `--max-findings 1000`.)")
        lines.append("")
        for f in info["listed"]:
            where = f"{f.get('file') or '(Projekt)'}" + (f":{f['line']}" if f.get("line") else "")
            fix = f" — Fix: {f['fix']}" if f.get("fix") else ""
            lines.append(f"- `{where}` {f.get('message', '')}{fix}".replace("\n", " "))
        lines.append("")
    return "\n".join(lines)


def run_triage_command(argv: list[str], prog: str = "ruttla") -> int:
    ap = argparse.ArgumentParser(
        prog=f"{prog} triage",
        description="Fix-Aufträge je Repo und Fix-Klasse aus Ruttla-JSON-Reports "
                    "(mechanical · catalog · judgement · security).",
        epilog="Exit: 0 Aufträge geschrieben (oder nichts zu tun) · 3 Fehler")
    ap.add_argument("reports", nargs="+", help="JSON-Reports (ruttla … --format json)")
    ap.add_argument("--out", required=True, help="Zielordner für die Aufträge")
    ap.add_argument("--base", help="Basis-Referenz für die Abnahme (Vorgabe: HEAD-SHA "
                                   "des Repos zum Zeitpunkt der Triage)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    try:
        table = load_table()
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        index = []
        for path in args.reports:
            report = json.loads(Path(path).read_text(encoding="utf-8"))
            for task in tasks_from_report(report, table):
                base = args.base or _head(task["root"]) or "HEAD"
                name = f"{_SAFE.sub('_', Path(task['root']).name)}__{task['class']}.md"
                (out / name).write_text(render_task(task, base), encoding="utf-8",
                                        newline="\n")
                index.append({"task": name, "root": task["root"], "class": task["class"],
                              "worker": WORKER[task["class"]], "base": base,
                              "checks": sorted(task["checks"]), "blocking_listed": task["blocking"],
                              "findings": sum(c["total"] for c in task["checks"].values())})
        (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8", newline="\n")
    except (OSError, ValueError, KeyError) as exc:
        print(f"ruttla triage: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    by_class = {c: sum(1 for t in index if t["class"] == c) for c in CLASSES}
    print(f"ruttla triage: {len(index)} Aufträge → {out} · "
          + " · ".join(f"{c} {n}" for c, n in by_class.items()))
    return 0
