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
