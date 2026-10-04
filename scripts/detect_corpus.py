#!/usr/bin/env python3
"""Referenzkorpus der Plattform-Erkennung (P10-T004) — tokenfrei.

Misst die Erkennung über echte Repos und vergleicht mit einem eingefrorenen
Soll-Stand. Der Soll-Stand nennt private Repos und gehört deshalb NICHT ins
Repo — auch nicht ignoriert, der Provenienz-Test liest den Arbeitsbaum —,
sondern unter $XDG_CONFIG_HOME/ruttla/detect_corpus.json (Standard ~/.config).

  detect_corpus.py --write [SOLL] REPO...   Soll-Stand neu schreiben
  detect_corpus.py --check [SOLL]           gegen den Soll-Stand messen

Exit 0 = gleich · 1 = abweichend (Diff je Repo) · 2 = nicht gemessen
(kein Soll-Stand, null Repos, oder ein Repo fehlt auf diesem Rechner).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ruttla.config import Config  # noqa: E402
from ruttla.context import Context  # noqa: E402
from ruttla.models import GateInputError  # noqa: E402

DEFAULT_SNAPSHOT = (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
                    / "ruttla" / "detect_corpus.json")


def measure(root: str) -> dict:
    try:
        ctx = Context(root=root, config=Config.load(root, None))
        out: dict = {"platforms": sorted(ctx.detected_platforms())}
        roots = getattr(ctx, "project_roots", None)
        if roots is not None:
            out["roots"] = [r.to_dict() for r in roots()]
        return out
    except GateInputError as exc:
        return {"error": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    ap.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    ap.add_argument("repos", nargs="*")
    args = ap.parse_args()
    snap = Path(args.snapshot)

    if args.write:
        if not args.repos:
            print("NICHT GEMESSEN: null Repos angegeben.")
            return 2
        data = {os.path.abspath(r): measure(os.path.abspath(r)) for r in args.repos}
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Soll-Stand geschrieben: {len(data)} Repos → {snap}")
        return 0

    if not snap.is_file():
        print(f"NICHT GEMESSEN: kein Soll-Stand unter {snap}")
        return 2
    expected = json.loads(snap.read_text(encoding="utf-8"))
    if not expected:
        print("NICHT GEMESSEN: Soll-Stand ist leer.")
        return 2
    missing = [r for r in expected if not os.path.isdir(r)]
    diverged = 0
    for root, want in sorted(expected.items()):
        if root in missing:
            continue
        got = measure(root)
        if got != want:
            diverged += 1
            print(f"ABWEICHEND {root}")
            for key in sorted(set(want) | set(got)):
                if want.get(key) != got.get(key):
                    print(f"   {key}: soll {want.get(key)}")
                    print(f"   {key}: ist  {got.get(key)}")
    measured = len(expected) - len(missing)
    print(f"{measured} gemessen, {diverged} abweichend, {len(missing)} fehlen")
    if diverged:
        return 1
    if missing:
        print("NICHT GEMESSEN: " + ", ".join(missing))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
