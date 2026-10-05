#!/usr/bin/env python3
"""Umgebungs- und Testgate der Rust-Engine (ADR-0011, P11-T001) — tokenfrei.

Prüft, ob die Toolchain die gemessene ``rust-version`` aus engine/Cargo.toml
erreicht, und lässt dann ``cargo test --locked`` laufen.

Exit 0 = bestanden · 1 = durchgefallen · 2 = nicht gemessen (Toolchain fehlt
oder ist älter als die MSRV). ``--require`` macht aus "nicht gemessen" ein
Durchfallen — für CI, wo die Toolchain installiert sein MUSS.

"Null Tests gelaufen" ist rot, nicht grün: ein Runner, der nur den Exit-Code
von cargo liest, verbucht einen leeren Lauf als bestanden.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "engine"

EXIT_OK, EXIT_FAILED, EXIT_UNMEASURED = 0, 1, 2
# Ein hängender Testprozess darf den Lauf nicht offen halten; die Ausgabe geht
# deshalb in eine Datei, nie in eine Pipe.
CARGO_TIMEOUT_S = 900

_VERSION = re.compile(r"\brustc (\d+)\.(\d+)(?:\.(\d+))?")
_RESULT = re.compile(r"^test result: \w+\. (\d+) passed; (\d+) failed", re.M)


def msrv(cargo_toml: Path = ENGINE / "Cargo.toml") -> tuple[int, ...]:
    data = tomllib.loads(cargo_toml.read_text(encoding="utf-8"))
    raw = data["package"]["rust-version"]
    return tuple(int(p) for p in raw.split("."))


def parse_rustc_version(text: str) -> tuple[int, ...] | None:
    m = _VERSION.search(text)
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())


def toolchain_state(rustc_output: str | None, required: tuple[int, ...]) -> tuple[int, str]:
    """Reine Entscheidung: (Exit, Grund) aus der rustc-Ausgabe und der MSRV."""
    need = ".".join(map(str, required))
    hint = f"rustup toolchain install stable (mindestens {need})"
    if rustc_output is None:
        return EXIT_UNMEASURED, f"rustc/cargo nicht gefunden — {hint}"
    have = parse_rustc_version(rustc_output)
    if have is None:
        return EXIT_UNMEASURED, f"rustc-Version nicht lesbar: {rustc_output.strip()!r}"
    padded = required + (0,) * (3 - len(required))
    if have < padded:
        return EXIT_UNMEASURED, (f"rustc {'.'.join(map(str, have))} ist älter als "
                                 f"rust-version {need} — {hint}")
    return EXIT_OK, f"rustc {'.'.join(map(str, have))} ≥ {need}"


def count_tests(cargo_output: str) -> tuple[int, int]:
    passed = failed = 0
    for p, f in _RESULT.findall(cargo_output):
        passed += int(p)
        failed += int(f)
    return passed, failed


def _rustc_output() -> str | None:
    rustc, cargo = shutil.which("rustc"), shutil.which("cargo")
    if not rustc or not cargo:
        return None
    try:
        return subprocess.run([rustc, "--version"], capture_output=True,
                              text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def run_cargo_tests() -> tuple[int, str]:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
        try:
            proc = subprocess.run(
                ["cargo", "test", "--locked", "--quiet"], cwd=ENGINE,
                stdout=log, stderr=subprocess.STDOUT, timeout=CARGO_TIMEOUT_S,
            )
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = None
        log.seek(0)
        out = log.read()
    if code is None:
        return EXIT_FAILED, f"cargo test nach {CARGO_TIMEOUT_S}s abgebrochen"
    passed, failed = count_tests(out)
    if code != 0 or failed:
        tail = "\n".join(out.splitlines()[-30:])
        return EXIT_FAILED, f"cargo test fehlgeschlagen (Exit {code}):\n{tail}"
    if passed == 0:
        return EXIT_FAILED, "cargo test: null Tests gelaufen — das ist kein Bestehen"
    return EXIT_OK, f"cargo test: {passed} Tests bestanden"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--require", action="store_true",
                    help="fehlende Toolchain = durchgefallen statt nicht gemessen")
    args = ap.parse_args(argv)

    code, why = toolchain_state(_rustc_output(), msrv())
    if code != EXIT_OK:
        label = "DURCHGEFALLEN" if args.require else "NICHT GEMESSEN"
        print(f"engine-gate: {label}: {why}")
        return EXIT_FAILED if args.require else code
    print(f"engine-gate: Toolchain {why}")

    code, why = run_cargo_tests()
    print(f"engine-gate: {'BESTANDEN' if code == EXIT_OK else 'DURCHGEFALLEN'}: {why}")
    return code


if __name__ == "__main__":
    os.environ.setdefault("CARGO_TERM_COLOR", "never")
    sys.exit(main())
