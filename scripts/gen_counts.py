#!/usr/bin/env python3
"""Zählwerte aus der Messung statt getippt (Paket R1-3).

Misst Regeln und Packs (Katalog), Sabotage-Proben und Checks (`ruttla --self-test`)
sowie die gesammelten Unittests (Collect, ohne Lauf) und schreibt sie in die
markierten Blöcke der Doku. Eine Quelle: die Vorlagen unten.

    python scripts/gen_counts.py           # Blöcke schreiben
    python scripts/gen_counts.py --check   # CI: Exit 1, wenn eine Zahl abweicht

Exit: 0 aktuell bzw. geschrieben · 1 Abweichung · 2 nicht gemessen.
Exit 2 ist nie Erfolg: fehlende Messung, fehlender Marker, Null als Ergebnis.
docs/RULES.md bleibt bei `gen_rule_docs.py` (dort schon generiert und gegated).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BEGIN = "<!-- ruttla:counts:begin -->"
END = "<!-- ruttla:counts:end -->"
SELFTEST_TIMEOUT_S = 900


class Unmeasured(Exception):
    """Eine Zahl ließ sich nicht ehrlich messen — Exit 2, nie grün."""


@dataclass(frozen=True)
class Target:
    path: str  # relativ zum Repo
    template: str  # Zeilen zwischen BEGIN und END; {Schlüssel} aus measure()


# Eine Quelle für alle Zählwerte-Blöcke. Neue Zählwerte nur hier erfassen.
TARGETS = (
    Target("README.md",
           "> Zählwerte (generiert): {rules} Regeln in {packs} Packs · "
           "{probes_ok}/{probes_total} Sabotage-Proben · {tests} Tests gesammelt\n"),
    Target("STATUS.md",
           "- Tests gesammelt: {tests} (Collect, nicht ausgeführt)\n"
           "- self-test: {probes_ok}/{probes_total} Proben, {checks_with_probes}/{checks} Checks in beiden Richtungen\n"),
    Target("docs/TESTING.md",
           "- {tests} Runner-Unittests (gesammelt)\n"
           "- {probes_ok}/{probes_total} Self-Test-Proben\n"
           "- {checks_with_probes}/{checks} Checks mit beiden Richtungen\n"),
    Target("docs/CURRENT_STATE.md",
           "- {checks_with_probes} von {checks} Checks besitzen Self-Test-Proben\n"),
)

_BLOCK = re.compile(re.escape(BEGIN) + r"\n(.*?)" + re.escape(END), re.DOTALL)
_SELF_CHECKS = re.compile(r"(\d+) Checks registriert, (\d+) mit Sabotage-Proben")
_SELF_PROBES = re.compile(r"BESTANDEN: (\d+)/(\d+) Sabotage-Proben")


def _positive(name: str, value: int) -> int:
    if value <= 0:
        raise Unmeasured(f"{name} = {value}: ungültig, nochmal messen")
    return value


def measure(root: Path = REPO) -> dict[str, int]:
    """Liefert alle Zählwerte oder wirft Unmeasured."""
    src = str(root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from ruttla.catalog import catalog
    from ruttla.engine import load_checks
    from ruttla.stats import ENV_DIR

    load_checks()
    rules = catalog()
    counts: dict[str, int] = {
        "rules": _positive("Regeln", len(rules)),
        "packs": _positive("Packs", len({r["pack"] for r in rules})),
    }

    with tempfile.TemporaryDirectory(prefix="gen-counts-stats-") as stats:
        env = dict(os.environ, PYTHONPATH=src, **{ENV_DIR: stats})
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "ruttla", "--self-test"],
                cwd=root, env=env, capture_output=True, text=True,
                timeout=SELFTEST_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise Unmeasured(f"--self-test Timeout nach {exc.timeout} s") from exc
    if proc.returncode != 0:
        raise Unmeasured(f"--self-test Exit {proc.returncode}")
    out = proc.stdout
    m_checks = _SELF_CHECKS.search(out)
    m_probes = _SELF_PROBES.search(out)
    if not m_checks or not m_probes:
        raise Unmeasured("--self-test-Ausgabe nicht lesbar")
    counts["checks"] = _positive("Checks", int(m_checks.group(1)))
    counts["checks_with_probes"] = int(m_checks.group(2))
    counts["probes_ok"] = int(m_probes.group(1))
    counts["probes_total"] = _positive("Proben", int(m_probes.group(2)))
    if counts["probes_ok"] != counts["probes_total"]:
        raise Unmeasured("Self-Test nicht vollständig grün")

    tests_dir = root / "tests"
    for entry in (str(tests_dir), src):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    suite = unittest.TestLoader().discover(str(tests_dir), top_level_dir=str(tests_dir))
    counts["tests"] = _positive("Tests", suite.countTestCases())
    return counts


def render(template: str, counts: dict[str, int]) -> str:
    return template.format(**counts)


def apply(text: str, template: str, counts: dict[str, int], label: str) -> str:
    """Ersetzt den Block; ohne genau einen Marker-Block: Unmeasured."""
    found = _BLOCK.findall(text)
    if len(found) != 1:
        raise Unmeasured(f"{label}: {len(found)} Marker-Blöcke statt 1")
    body = render(template, counts)
    return _BLOCK.sub(lambda _m: BEGIN + "\n" + body + END, text, count=1)


def run(root: Path, counts: dict[str, int], targets: tuple[Target, ...], check: bool) -> int:
    stale: list[str] = []
    for target in targets:
        path = root / target.path
        if not path.exists():
            raise Unmeasured(f"{target.path} fehlt")
        text = path.read_text(encoding="utf-8")
        new = apply(text, target.template, counts, target.path)
        if new != text:
            stale.append(target.path)
            if not check:
                path.write_text(new, encoding="utf-8", newline="\n")
    if check:
        if stale:
            print("Zählwerte weichen von der Messung ab: " + ", ".join(stale)
                  + " — python scripts/gen_counts.py", file=sys.stderr)
            return 1
        print("Zählwerte aktuell.")
        return 0
    print("geschrieben: " + (", ".join(stale) if stale else "keine Änderung"))
    return 0


def main(argv: list[str]) -> int:
    check = "--check" in argv
    try:
        counts = measure()
        return run(REPO, counts, TARGETS, check)
    except Unmeasured as exc:
        print(f"NICHT GEMESSEN: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
