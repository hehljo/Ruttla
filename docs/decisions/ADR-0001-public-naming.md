# ADR-0001 — Public Naming and Distribution Namespace

## Status
Accepted — 2026-09-24 (maintainer decision)

## Context
The repository is called `CODE_QUALITY_GENERAL`; the CLI was `master_gate.py`;
the JSON report called the tool `master_quality_gate`; the project profile is
`.qualitygate.toml`. `qualitygate` is already taken on PyPI by an unrelated
project.

## Decision

**Ruttla** — from German *rütteln*, "to shake". A normal linter looks at your
code; Ruttla shakes it: every rule must survive a counter-probe that tries to
make it fail, and a run that measured nothing never claims that everything is
fine.

| Surface | Name |
|---|---|
| Brand / product | Ruttla |
| PyPI distribution | `ruttla` |
| Python import package | `ruttla` |
| CLI executable | `ruttla` (plus `python -m ruttla`) |
| Project profile | `.ruttla.toml` |
| GitHub Action identity | not published in 0.1 (see ADR-0009) |
| Repository | stays `CODE_QUALITY_GENERAL` while private; rename at public launch |

## Namespace check (2026-09-24)
- `https://pypi.org/pypi/ruttla/json` → HTTP 404 (name free).
- No trademark search beyond a web/registry spot check was performed; repeat
  before the public 0.1.0 release (P08).

## Migration aliases

| Legacy | Status in 0.x | Removal |
|---|---|---|
| `python3 master_gate.py …` | thin shim onto `ruttla.cli:main`, identical behaviour | not before 1.0 / two minor releases after deprecation notice |
| `import core` / `from core import …` (repo checkout only) | alias module onto `ruttla.core` | with the shim |
| `.qualitygate.toml` | still read when no `.ruttla.toml` exists; both present → config error | 1.0 |
| JSON `"tool": "master_quality_gate"` | kept for report schema 1.x; `tool_name: "ruttla"` added | report schema 2.0 |

## Why
Naming collisions are much harder to fix after users pin package, CLI and
config identifiers. A single name across distribution, import and CLI keeps
the documentation mapping trivial.

## Consequences
- PyPI metadata uses `ruttla`; nothing is published while the repo is private.
- The JSON `tool` field keeps its old value until a schema major bump, so
  existing consumers do not break.

## Validation
- `ruttla --version`, `python -m ruttla --version` and `python3 master_gate.py --version`
  print the same version (tests/test_package.py).
- Config alias covered by unit tests.
