#!/usr/bin/env python3
"""Gerüst einer deklarativen Regel aus einem Python-Check (P11-T008) — tokenfrei.

  port_rule.py CHECK_ID [--force]

Schreibt ``src/ruttla/rules/<platform>/<CHECK_ID>.toml`` mit allen Metadaten
und den Sabotage-Proben des Python-Checks als Fixtures — unverändert, sie
sind das Orakel. ``pattern``, ``message`` und ``scope`` füllt der Portierende;
ein leeres Muster lässt die Engine das Laden verweigern, ein halb fertiges
Gerüst kann also nicht still mitlaufen.

Danach (docs/RULE_FORMAT.md, Abschnitt "Port"):
  1. Felder füllen, ``ruttla-engine selftest --rules src/ruttla/rules --rule ID``
  2. ``python3 scripts/engine_diff.py findings`` — Python vs. Engine, identisch
  3. Python-Check löschen, ``ruttla --self-test`` — Probenzahl unverändert
"""
from __future__ import annotations

import argparse
import inspect
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ruttla.engine import load_checks  # noqa: E402
from ruttla.registry import BASELINE_VERSION, REGISTRY  # noqa: E402


def toml_str(text: str) -> str:
    """TOML-String, der jeden Inhalt exakt zurückgibt (mehrzeilig lesbar)."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    body = "".join(out)
    # Leerraum am Zeilenende escapen: der Inhalt bleibt exakt, und die Datei
    # besteht git diff --check (Fixtures für Trailing-Whitespace-Regeln).
    body = re.sub(r"[ ]+(?=\n|$)", lambda m: "\\u0020" * len(m.group(0)), body)
    if "\n" in text:
        # Der Umbruch direkt nach """ wird von TOML verworfen — Inhalt bleibt exakt.
        return '"""\n' + body + '"""'
    return '"' + body + '"'


def skeleton(check_id: str) -> str:
    c = REGISTRY[check_id]
    lines = [
        'format = "ruttla-rule/0"',
        f"id = {toml_str(c.id)}",
        f"title = {toml_str(c.title)}",
        f"platform = {toml_str(c.platform)}",
        f"severity = {toml_str(c.default_severity.value)}",
    ]
    if c.guideline:
        lines.append(f"guideline = {toml_str(c.guideline)}")
    rationale = c.rationale_text()
    if rationale:
        lines.append(f"rationale = {toml_str(rationale)}")
    if c.references:
        lines.append("references = [" + ", ".join(toml_str(r) for r in c.references) + "]")
    if c.tags:
        lines.append("tags = [" + ", ".join(toml_str(t) for t in c.tags) + "]")
    if c.safe_by_default:
        lines.append("safe_by_default = true")
    if c.introduced_in != BASELINE_VERSION:
        lines.append(f"introduced_in = {toml_str(c.introduced_in)}")
    if c.lifecycle != "stable":
        lines.append(f"lifecycle = {toml_str(c.lifecycle)}")
    lines += [
        "",
        "[scope]",
        'extensions = []  # TODO aus dem Python-Check',
        'unit_label = "TODO"',
        "",
        "[match]",
        "pattern = ''  # TODO — leer lässt die Engine das Laden verweigern",
        'message = "TODO"',
        "",
        "# --- Python-Quelle (nur zum Portieren; vor dem Commit löschen) ---",
    ]
    for src in inspect.getsource(c.fn).splitlines():
        lines.append("# " + src)
    for case in c.self_tests:
        lines += ["", "[[fixtures]]", f"name = {toml_str(case.name)}",
                  f"expect = {toml_str(case.expect.value)}"]
        if case.expect_finding_contains is not None:
            lines.append(f"expect_finding_contains = {toml_str(case.expect_finding_contains)}")
        lines.append("[fixtures.files]")
        for rel, content in sorted(case.files.items()):
            lines.append(f"{toml_str(rel)} = {toml_str(content)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("check_id")
    ap.add_argument("--force", action="store_true", help="vorhandene Datei überschreiben")
    args = ap.parse_args(argv)
    load_checks()
    check = REGISTRY.get(args.check_id)
    if check is None or check.engine:
        print(f"{args.check_id}: kein Python-Check registriert")
        return 3
    text = skeleton(args.check_id)
    # Rundlauf: die Fixtures müssen exakt die Python-Proben sein.
    data = tomllib.loads(text)
    got = [(f["name"], f["files"], f["expect"], f.get("expect_finding_contains"))
           for f in data["fixtures"]]
    want = [(c.name, c.files, c.expect.value, c.expect_finding_contains) for c in check.self_tests]
    if got != want:
        print("Rundlauf der Fixtures weicht ab — Gerüst nicht geschrieben")
        return 1
    dest = REPO / "src" / "ruttla" / "rules" / check.platform / f"{check.id}.toml"
    if dest.exists() and not args.force:
        print(f"{dest.relative_to(REPO)} existiert (--force zum Überschreiben)")
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    print(f"{dest.relative_to(REPO)}: {len(want)} Fixtures übernommen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
