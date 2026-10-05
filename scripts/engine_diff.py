#!/usr/bin/env python3
"""Differenz-Gate Python ↔ Rust-Engine (ADR-0011) — tokenfrei.

  engine_diff.py inventory [REPO...]   Dateiinventar vergleichen (P11-T002)
  engine_diff.py detect [REPO...]      Plattformen + Projektwurzeln (P11-T003)

Ohne REPO werden die Repos des Referenzkorpus genommen
(~/.config/ruttla/detect_corpus.json, siehe detect_corpus.py).

Exit 0 = identisch · 1 = abweichend (Diff je Repo) · 2 = nicht gemessen
(kein Engine-Binary, null Repos, oder ein Repo fehlt auf diesem Rechner).
Null verglichene Repos sind nie "identisch".
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ruttla.config import Config  # noqa: E402
from ruttla.context import Context  # noqa: E402
from ruttla.discovery import inventory  # noqa: E402
from ruttla.models import GateInputError  # noqa: E402

EXIT_OK, EXIT_DIFF, EXIT_UNMEASURED = 0, 1, 2
ENGINE_TIMEOUT_S = 600

_ERROR_KINDS = (
    ("Eingabeverzeichnis nicht lesbar", "unreadable_dir"),
    ("Eingabedatei nicht", "unreadable_file"),
    ("Eingabepfad verlässt die Prüfwurzel", "outside_root"),
)


def default_engine() -> Path | None:
    """RUTTLA_ENGINE_BIN, sonst das jüngste Build unter engine/target.

    Das jüngste, nicht das "beste": ein veraltetes Release-Binary neben einem
    frischen Debug-Build würde sonst den alten Stand messen.
    """
    override = os.environ.get("RUTTLA_ENGINE_BIN")
    if override:
        return Path(override)
    candidates = [REPO / "engine" / "target" / profile / name
                  for profile in ("release", "debug")
                  for name in ("ruttla-engine", "ruttla-engine.exe")]
    built = [c for c in candidates if c.is_file()]
    return max(built, key=lambda c: c.stat().st_mtime) if built else None


def _error(message: str) -> dict:
    kind = next((k for prefix, k in _ERROR_KINDS if message.startswith(prefix)), "unknown")
    # Der OS-Fehlertext ist plattformabhängig; verglichen werden Art und,
    # bei Wurzelverletzung, die vollständige (deterministische) Meldung.
    return {"error": {"kind": kind,
                      "message": message if kind == "outside_root" else None}}


def python_inventory(root: str, config: Config) -> dict:
    try:
        files, coverage = inventory(root, config)
    except GateInputError as exc:
        return _error(str(exc))
    return {"files": [{"rel": f.rel, "ext": f.ext} for f in files],
            "coverage": coverage.to_dict()}


def _engine_args(config: Config) -> list[str]:
    cmd = ["--max-file-bytes", str(config.max_file_bytes)]
    for d in config.exclude_dirs:
        cmd += ["--exclude-dir", d]
    for g in config.exclude_globs:
        cmd += ["--exclude-glob", g]
    return cmd


def _run_engine(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          timeout=ENGINE_TIMEOUT_S)
    if proc.returncode not in (0, 2):
        raise RuntimeError(f"ruttla-engine Exit {proc.returncode}: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    if "error" in data:
        return _error(data["error"]["message"])
    return data


def engine_inventory(binary: Path, root: str, config: Config) -> dict:
    return _run_engine([str(binary), "inventory", root, *_engine_args(config)])


def python_detect(root: str, config: Config) -> dict:
    try:
        ctx = Context(root=root, config=config)
        return {"platforms": sorted(ctx.detected_platforms()),
                "roots": [r.to_dict() for r in ctx.project_roots()]}
    except GateInputError as exc:
        return _error(str(exc))


def engine_detect(binary: Path, root: str, config: Config, manifest: str | None = None) -> dict:
    extra = ["--manifest", manifest] if manifest else []
    return _run_engine([str(binary), "detect", root, *extra, *_engine_args(config)])


def diff(a: dict, b: dict, limit: int = 8) -> list[str]:
    """Lesbare Unterschiede (Python links, Rust rechts)."""
    if a == b:
        return []
    out: list[str] = []
    if "error" in a or "error" in b:
        return [f"python={a.get('error')} rust={b.get('error')}"]
    if "platforms" in a:
        return [f"{key}: python={a.get(key)} rust={b.get(key)}"
                for key in ("platforms", "roots") if a.get(key) != b.get(key)]
    pa = [f["rel"] for f in a["files"]]
    pb = [f["rel"] for f in b["files"]]
    for rel in sorted(set(pa) - set(pb))[:limit]:
        out.append(f"nur Python: {rel}")
    for rel in sorted(set(pb) - set(pa))[:limit]:
        out.append(f"nur Rust: {rel}")
    if not out and pa != pb:
        out.append("gleiche Dateien, andere Reihenfolge")
    if a["files"] != b["files"] and not out:
        out.append("Endungen weichen ab")
    for key in sorted(set(a["coverage"]) | set(b["coverage"])):
        if a["coverage"].get(key) != b["coverage"].get(key):
            out.append(f"coverage.{key}: python={a['coverage'].get(key)!r} "
                       f"rust={b['coverage'].get(key)!r}"[:300])
    return out


def corpus_repos() -> list[str]:
    snap = (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
            / "ruttla" / "detect_corpus.json")
    if not snap.is_file():
        return []
    data = json.loads(snap.read_text(encoding="utf-8"))
    repos = data.get("repos", data)
    return sorted(repos) if isinstance(repos, dict) else sorted(repos)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["inventory", "detect"])
    ap.add_argument("repos", nargs="*")
    args = ap.parse_args(argv)

    binary = default_engine()
    if binary is None:
        print("NICHT GEMESSEN: ruttla-engine nicht gebaut (cargo build in engine/)")
        return EXIT_UNMEASURED
    repos = args.repos or corpus_repos()
    if not repos:
        print("NICHT GEMESSEN: null Repos (kein Korpus-Soll-Stand, keine Argumente)")
        return EXIT_UNMEASURED
    missing = [r for r in repos if not os.path.isdir(r)]
    if missing:
        print(f"NICHT GEMESSEN: {len(missing)} Repo(s) fehlen: {', '.join(missing[:5])}")
        return EXIT_UNMEASURED

    diverged = 0
    files = 0
    for repo in repos:
        root = os.path.abspath(repo)
        try:
            config = Config.load(root, None)
        except GateInputError as exc:
            config = Config()
            print(f"  · {repo}: Profil ungültig ({exc}) — Vorgaben verwendet")
        if args.what == "inventory":
            a = python_inventory(root, config)
            b = engine_inventory(binary, root, config)
            files += len(a.get("files", []))
        else:
            a = python_detect(root, config)
            b = engine_detect(binary, root, config)
        problems = diff(a, b)
        if problems:
            diverged += 1
            print(f"✗ {repo}")
            for p in problems:
                print(f"    {p}")
    detail = f", {files} Dateien verglichen" if args.what == "inventory" else ""
    print(f"{args.what}: {len(repos) - diverged}/{len(repos)} Repos identisch{detail}")
    return EXIT_DIFF if diverged else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
