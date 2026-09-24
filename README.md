<p align="center">
  <img src="docs/icon/logo.svg" alt="Ruttla Logo" width="140">
</p>

# Ruttla

**Ruttla** comes from the German *rütteln* ("to shake") — and the woodpecker metaphor.

A normal linter looks at the bark. Ruttla behaves like a woodpecker tapping
against the trunk: it knocks firmly against the code structure until hidden
hollows, bugs and brittle spots become audible — shaking out flaws that passive
reading never catches.

*Code → Structure → Ruttla taps → Weak spots resonate.*

It doesn't just check whether a rule turns green — it actively tries to make
every rule fail with a counter-probe. And when nothing was measured, Ruttla
never claims that everything is fine.

---

Ruttla is a **local, deterministic quality gate**: executable engineering
memory for failures that normal linters miss. A real failure happens → its
cause is proven → a deterministic rule is written → a broken **and** a healthy
probe must both behave → from then on the failure costs no debugging or
agent tokens. No LLM, no network, no telemetry; the scanned code is read,
never executed.

> Status: 0.1.0.dev0, private pre-release. German version: [README.de.md](README.de.md).

## 30-second start

```bash
python -m pip install "ruttla @ git+https://github.com/hehljo/Ruttla@main"  # until PyPI
ruttla path/to/project                 # human-readable report
ruttla . --format agent                # one line per finding, for scripts and agents
ruttla . --format json                 # full report (schemas/report.schema.json)
ruttla . --sarif ruttla.sarif          # SARIF 2.1.0 for GitHub code scanning
ruttla . --changed-only origin/main    # only changed + untracked files
ruttla --list [--format json|markdown] # rule catalog
ruttla --explain secrets.hardcoded_credential
ruttla --self-test                     # shake the gates themselves
```

From a checkout without installing: `python3 master_gate.py …` (identical).

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | measured, no blocking finding (advisory findings may exist) |
| 1 | at least one **blocking** finding |
| 2 | **nothing was measured** — not a success |
| 3 | runner, input, config or plugin error |

Capture the status before filtering: `ruttla . | head` reports `head`'s status.

```bash
out=$(ruttla . --format agent); status=$?
```

Every finding carries `blocking: true|false`. Without a profile only rules
marked *safe by default* block; with a profile every `error` blocks; with
`--strict` every finding blocks. Details: [docs/CONTRACTS.md](docs/CONTRACTS.md).

## Profile: `.ruttla.toml`

```toml
config_version = 1

[gate]
strict = false
exclude = ["legacy/**", "extracted/**"]   # glob on the relative path
max_file_bytes = 2000000                   # larger files are reported as skipped

[project]
platform = "apple"          # force a rule pack on (in addition to detection)

[brand]
names = ["Acme"]
sources = ["src/brand.ts"]

[severity]
"secrets.*" = "error"
"godot.untyped_declaration" = "off"
```

The legacy name `.qualitygate.toml` is still read; both files at once is an error.

## What makes it different

- **Four honest states:** pass, fail, unmeasured (with a reason), error. "Zero
  files checked" is never green.
- **Self-tested rules:** 90 rules, 206 probes; every rule must FAIL on its
  broken probe and PASS on its healthy probe (`ruttla --self-test`).
- **Evidence-backed catalog:** rules come from real failures, see
  [docs/RULES.md](docs/RULES.md), [docs/GUIDELINES.md](docs/GUIDELINES.md) and
  [LESSONS_LEARNED.md](LESSONS_LEARNED.md).
- **Coverage is visible:** skipped oversize files and platforms without a rule
  pack are reported, not silently dropped.
- **Agent-native output:** stable check IDs, compact agent format, JSON, SARIF.

Packs: universal (brand, i18n, secrets, gates, docs, media, protocol), apple
(incl. App Store release), web, python services, raspberry, godot, unreal.

## Coexistence with other tools

Ruttla does **not** replace compilers, CodeQL / GitHub Code Quality, Ruff,
ESLint or SwiftLint. Use those for the mainstream issues they cover well; use
Ruttla for cross-toolchain failure classes, release/store workflows and
project knowledge they don't encode. Upload each tool's SARIF under its own
category ([docs/integrations/github-actions.md](docs/integrations/github-actions.md)).

Known limitation: rule messages are currently German.

## Privacy and trust

Offline, no telemetry. The scan target is untrusted data: nothing from it is
imported or executed, and symlinks may not leave the scan root. Rules load
only from the installed package (ADR-0005).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — a new rule needs a real failure, a
broken and a healthy probe, a false-positive analysis and a fix hint that only
names APIs that exist. Security: [SECURITY.md](SECURITY.md). Roadmap:
[MASTER_ROADMAP.md](MASTER_ROADMAP.md). License: Apache-2.0.
