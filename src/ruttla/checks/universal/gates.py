"""Universal: gates and test runners must not report a false green.

Split from the original checks/universal.py; background and
shared helpers in _common.py.
"""

from __future__ import annotations

import os
import re

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    register,
    result_for,
    SelfTestCase,
    Severity,
    snippet,
    Status,
    strip_comments,
    unmeasured,
)


# ===========================================================================
# Gate-Hygiene: die Pipe-Falle
# ===========================================================================

@register(
    "gate.pipe_swallows_exit_status",
    "Exit-Status wird durch eine Pipe verfälscht",
    severity=Severity.ERROR,
    guideline="CLAUDE.md § Gates — 'Ein tail vor der Statusprüfung verschluckt die Gegenprobe'",
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="Pipe vor Statusprüfung",
            files={"run.sh": '#!/bin/bash\npython3 gate.py 2>&1 | head -3\necho "EXIT: $?"\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Status aus Variable",
            files={"run.sh": '#!/bin/bash\nout=$(python3 gate.py 2>&1)\nstatus=$?\necho "$out" | head -3\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_pipe_exit(ctx: Context) -> CheckResult:
    """Der Status einer Pipeline ist der des LETZTEN Glieds.

    Belegt am 13.09.2026: drei Sabotage-Läufe meldeten alle EXIT: 0, auch die
    mit sichtbarem FEHLER — der Status war der von `head`.

    Warnzeichen laut Guideline: in einer Prüfzeile stehen `|` und `$?` beide.
    """
    title = "Exit-Status wird durch eine Pipe verfälscht"
    findings: list[Finding] = []
    units = 0
    swallowing = re.compile(r"\|\s*(head|tail|grep|awk|sed|cut|sort|uniq|jq|tee|wc)\b")
    for sf in ctx.all_files():
        base = os.path.basename(sf.rel)
        if sf.ext not in (".sh", ".bash", ".zsh") and not base.endswith(("Makefile", "makefile")):
            if sf.ext not in (".yml", ".yaml") or "workflow" not in sf.rel.lower():
                continue
        units += 1
        lines = sf.lines
        for idx, raw in enumerate(lines, start=1):
            code = raw.split("#", 1)[0]
            if "pipefail" in raw:
                continue
            # Fall 1: | und $? in derselben Zeile
            if swallowing.search(code) and "$?" in code:
                findings.append(Finding(
                    check_id="gate.pipe_swallows_exit_status",
                    severity=Severity.ERROR,
                    message="Pipe und $? in derselben Zeile — $? ist der Status des letzten Glieds.",
                    file=sf.rel, line=idx, evidence=snippet(raw),
                    fix="Ausgabe in eine Variable, Status sofort danach lesen, "
                        "dann erst filtern.",
                    guideline="CLAUDE.md § Gates",
                ))
                continue
            # Fall 2: gepipete Zeile, direkt danach wird $? gelesen
            if swallowing.search(code) and idx < len(lines):
                nxt = lines[idx].split("#", 1)[0]
                if "$?" in nxt:
                    findings.append(Finding(
                        check_id="gate.pipe_swallows_exit_status",
                        severity=Severity.ERROR,
                        message="$? unmittelbar nach einer Pipe gelesen — "
                                "das ist der Status des Filters, nicht des Gates.",
                        file=sf.rel, line=idx + 1, evidence=snippet(nxt),
                        fix="Ausgabe in eine Variable, Status sofort danach, "
                            "dann filtern. Oder `set -o pipefail` setzen.",
                        guideline="CLAUDE.md § Gates",
                    ))
    if units == 0:
        return unmeasured("gate.pipe_swallows_exit_status", title,
                          "Keine Shell-Skripte, Makefiles oder Workflows gefunden.")
    return result_for("gate.pipe_swallows_exit_status", title, findings, units,
                      "Skripte")


@register(
    "gate.runner_accepts_zero_tests",
    "Test-Runner wertet 'null Tests gefunden' nicht als Fehler",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Gates — \"'Null Tests gefunden' ist rot, nicht grün\"",
    self_tests=[
        SelfTestCase(
            name="nur Exit-Code",
            files={"run_tests.sh": "#!/bin/bash\npytest tests/\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Testzahl geprueft",
            files={"run_tests.sh": "#!/bin/bash\nout=$(pytest tests/)\nif echo \"$out\" | grep -q 'no tests ran'; then\n  echo 'nicht gemessen'; exit 2\nfi\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_zero_tests(ctx: Context) -> CheckResult:
    """Jeder Sammel-Runner braucht einen dritten Ausgang. Ein Runner, der nur
    den Exit-Code liest, verbucht einen Abbruch als Erfolg."""
    title = "Test-Runner wertet 'null Tests gefunden' nicht als Fehler"
    runners: list[tuple[str, int, str]] = []
    test_cmd = re.compile(
        r"\b(pytest|deno\s+test|npm\s+(run\s+)?test|jest|vitest|swift\s+test"
        r"|dotnet\s+test|go\s+test|cargo\s+test|gdunit|gut)\b"
    )
    for sf in ctx.all_files():
        base = os.path.basename(sf.rel)
        is_runner = (
            sf.ext in (".sh", ".bash", ".zsh")
            or base in ("Makefile", "makefile")
            or (sf.ext in (".yml", ".yaml") and "workflow" in sf.rel.lower())
        )
        if not is_runner:
            continue
        for idx, raw in enumerate(sf.lines, start=1):
            if test_cmd.search(raw) and not raw.strip().startswith("#"):
                runners.append((sf.rel, idx, raw.strip()))
    if not runners:
        return unmeasured("gate.runner_accepts_zero_tests", title,
                          "Kein Test-Runner-Aufruf in Skripten/Workflows gefunden.")

    guard = re.compile(
        r"(?i)(0\s+(tests?|passed|collected|Dateien|gates?)"
        r"|no\s+tests?\s+(ran|found|collected)"
        r"|null\s+(tests?|gates?)"
        r"|keine\s+(tests?|gates?)"
        r"|collected\s+0"
        r"|test_count|tests_run|--?fail-?under|\bcount\b\s*[-=]eq\s*0"
        r"|nicht\s+gemessen|unmeasured)"
    )
    findings: list[Finding] = []
    for rel, line, evidence in runners:
        sf = next((f for f in ctx.all_files() if f.rel == rel), None)
        if sf and guard.search(sf.text):
            continue
        findings.append(Finding(
            check_id="gate.runner_accepts_zero_tests",
            severity=Severity.WARNING,
            message="Runner liest nur den Exit-Code — 'null Tests' sieht aus wie Erfolg.",
            file=rel, line=line, evidence=snippet(evidence),
            fix="Testzahl aus der Ausgabe lesen und 0 ausdrücklich als Fehler "
                "werten. Drei Ausgänge: bestanden / durchgefallen / nicht gelaufen.",
            guideline="CLAUDE.md § Gates",
        ))
    return result_for("gate.runner_accepts_zero_tests", title, findings,
                      len(runners), "Runner-Aufrufe")


@register(
    "gate.reads_from_gitignored_artifact",
    "Gate liest aus einem Verzeichnis, das in .gitignore steht",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § 'Ein Gate, das aus einem Artefakt liest, prüft den Stand des Artefakts'",
    self_tests=[
        SelfTestCase(
            name="Gate liest ignoriertes Artefakt",
            files={".gitignore": ".build/\n", "gates/check_x.mjs": "import { render } from '../.build/renderer.js';\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Gate liest die Quelle",
            files={".gitignore": ".build/\n", "gates/check_x.mjs": "import { render } from '../src/renderer.ts';\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_gate_artifact(ctx: Context) -> CheckResult:
    """Auf einem frischen Checkout existiert das Artefakt gar nicht — dann ist
    'nicht gemessen' der einzige ehrliche Ausgang."""
    title = "Gate liest aus einem Verzeichnis, das in .gitignore steht"
    gitignore = os.path.join(ctx.root, ".gitignore")
    if not os.path.isfile(gitignore):
        return unmeasured("gate.reads_from_gitignored_artifact", title,
                          "Keine .gitignore vorhanden.")
    try:
        with open(gitignore, "r", encoding="utf-8", errors="replace") as fh:
            ignored = [
                ln.strip().strip("/") for ln in fh
                if ln.strip() and not ln.strip().startswith("#")
                and not ln.strip().startswith("!")
            ]
    except OSError:
        return unmeasured("gate.reads_from_gitignored_artifact", title,
                          ".gitignore nicht lesbar.")
    ignored = [i for i in ignored if i and "*" not in i and "." != i and len(i) > 1]
    if not ignored:
        return unmeasured("gate.reads_from_gitignored_artifact", title,
                          "Keine konkreten Verzeichnisse in .gitignore.")

    gate_files = [
        # Hier ist die Gate-Datei der Prüfgegenstand — also ausdrücklich
        # die Fassung, die Regeldefinitionen einschließt.
        sf for sf in ctx.all_files()
        if re.search(r"(gate|check|verify|pruef|prüf|audit)", sf.rel, re.IGNORECASE)
        and sf.ext in (".py", ".js", ".mjs", ".ts", ".sh")
    ]
    if not gate_files:
        return unmeasured("gate.reads_from_gitignored_artifact", title,
                          "Keine Gate-/Prüfskripte im Projekt gefunden.")
    findings: list[Finding] = []
    for sf in gate_files:
        body = strip_comments(sf.text, sf.ext)
        for entry in ignored:
            pat = re.compile(r"[\"'`(\s/]" + re.escape(entry) + r"/")
            for m in pat.finditer(body):
                line_no = body.count("\n", 0, m.start()) + 1
                raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
                findings.append(Finding(
                    check_id="gate.reads_from_gitignored_artifact",
                    severity=Severity.WARNING,
                    message=f"Gate greift auf '{entry}/' zu, das in .gitignore steht.",
                    file=sf.rel, line=line_no, evidence=snippet(raw),
                    fix="Den Bau-Schritt in den Runner legen, unmittelbar vor das "
                        "Gate. Ein Befehl in der README ist Text zum Lesen, kein "
                        "Schritt zum Durchlaufen.",
                    guideline="CLAUDE.md § Gates",
                ))
                break
    return result_for("gate.reads_from_gitignored_artifact", title, findings,
                      len(gate_files), "Gate-Skripte")
