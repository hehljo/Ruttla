"""Explicit package updater for the ``ruttla update`` command.

Scanning remains offline. This opt-in command delegates installation to pip
in the active Python environment and never changes or pulls a source checkout.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from .engine import EXIT_CRASH, EXIT_OK

UPDATE_REQUIREMENT = "ruttla @ git+https://github.com/hehljo/Ruttla@main"


class UpdateArgumentParser(argparse.ArgumentParser):
    """Update-command usage errors follow the CLI's exit-3 contract."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_CRASH, f"RUNNER_ERROR\tinvalid_arguments\t{message}\n")


def run_update(argv: list[str], prog: str = "ruttla") -> int:
    """Install the current GitHub main branch into the active Python environment."""
    parser = UpdateArgumentParser(
        prog=f"{prog} update",
        description="Installiert den aktuellen Ruttla-Stand von GitHub in der aktiven Python-Umgebung.",
    )
    parser.parse_args(argv)

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--force-reinstall",
        UPDATE_REQUIREMENT,
    ]
    print("Aktualisiere Ruttla von GitHub (main) …")
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        print(f"Ruttla-Update konnte pip nicht starten: {exc}", file=sys.stderr)
        return EXIT_CRASH

    if result.returncode != 0:
        print(
            f"Ruttla-Update fehlgeschlagen (pip Exit {result.returncode}). "
            "Prüf die pip-Meldung oben und deine Python-Umgebung.",
            file=sys.stderr,
        )
        return EXIT_CRASH

    print("Ruttla ist aktualisiert. Starte den Befehl für den neuen Stand erneut.")
    return EXIT_OK
