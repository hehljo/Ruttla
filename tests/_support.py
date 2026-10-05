"""Shared test helpers: import path, CLI runner, temporary project trees."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
for entry in (str(SRC), str(REPO)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from ruttla.engine import load_checks  # noqa: E402
from ruttla.registry import REGISTRY  # noqa: E402


def ensure_checks_loaded() -> None:
    if not REGISTRY:
        load_checks()


def cli(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run the CLI exactly as a user would (``python -m ruttla``)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ruttla", *args],
        cwd=cwd, env=env, text=True, encoding="utf-8",
        capture_output=True, timeout=120,
    )


def cli_json(*args: str) -> tuple[int, dict]:
    proc = cli(*args, "--format", "json")
    return proc.returncode, json.loads(proc.stdout)


def make_tree(files: dict[str, str | bytes]) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    for rel, content in files.items():
        path = Path(tmp.name, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
    return tmp


ENGINE_DIR = REPO / "engine"


def engine_binary() -> Path | None:
    """The built Rust engine (ADR-0011), or None.

    ``RUTTLA_ENGINE_BIN`` overrides the location; otherwise the debug build
    under ``engine/target`` is used, which ``scripts/engine_gate.py`` builds.
    """
    override = os.environ.get("RUTTLA_ENGINE_BIN")
    if override:
        return Path(override)
    for profile in ("debug", "release"):
        for name in ("ruttla-engine", "ruttla-engine.exe"):
            candidate = ENGINE_DIR / "target" / profile / name
            if candidate.is_file():
                return candidate
    return None


def require_engine(case) -> Path:
    """Skip without an engine — unless RUTTLA_ENGINE_REQUIRED=1 (engine gate, CI).

    A skipped differential test is *not measured*; the engine gate sets the
    variable so that a missing binary fails instead of hiding as a skip.
    """
    binary = engine_binary()
    if binary is None:
        if os.environ.get("RUTTLA_ENGINE_REQUIRED") == "1":
            case.fail("ruttla-engine nicht gebaut, aber RUTTLA_ENGINE_REQUIRED=1")
        case.skipTest("ruttla-engine not built (cargo build in engine/) — not measured")
    return binary
