"""Ruttla — a local, deterministic quality gate that shakes your code.

A normal linter looks at your code; Ruttla shakes it. Every rule carries a
broken and a healthy counter-probe, and a run that measured nothing never
claims that everything is fine.

Public surfaces (see docs/CONTRACTS.md): the ``ruttla`` CLI, its exit codes,
check IDs, the ``.ruttla.toml`` profile and the JSON / agent / SARIF reports.
The Python API below the CLI is not yet a stable contract (0.x).
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]
