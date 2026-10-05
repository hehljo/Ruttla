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
agent tokens. Scanning uses no LLM, network, or telemetry; target code is read,
never executed. Network access happens only when explicitly running `ruttla update`.

> Status: 0.1.0.dev0, public preview. German version: [README.de.md](README.de.md).

## Built for Coding Agents & LLMs

Coding agents (Claude Code, Cursor, OpenAI Codex, GitHub Copilot, Aider, Windsurf) waste thousands of tokens looping on subtle bugs and linters' blind spots. Ruttla provides:

- **Token-dense output (`--format agent`)**: One line per finding with `file`, `line`, `severity`, and an exact, non-hallucinated fix instruction (`FIX: ...`).
- **Zero token burn**: Scans are offline and deterministic; no network calls or LLM queries unless you explicitly run `ruttla update`.
- **Strict exit contracts**: Differentiates between clean (`0`), blocking findings (`1`), unmeasured scopes (`2`), and runner errors (`3`). Never confuses "nothing checked" with success.

## 30-second start

```bash
curl -fsSL https://raw.githubusercontent.com/hehljo/Ruttla/main/install.sh | sh   # Linux, macOS
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

Windows (PowerShell): `irm https://raw.githubusercontent.com/hehljo/Ruttla/main/install.ps1 | iex`.
The installer creates its own Python environment (Python ≥ 3.11 required) and
installs the package **and** the matching Rust engine from the latest GitHub
release, checked against `SHA256SUMS`.

## One command, detection included

`ruttla .` needs no configuration. It detects the platforms from marker files
(`src/ruttla/platforms.toml`, e.g. `*.xcodeproj`, `package.json`,
`project.godot`, `*.csproj`) **per subproject**: in a monorepo an iOS app in
`ios/` and a web app in `web/` each get their own rule pack, and no rule sees
the files of another platform's subproject. Platforms without a rule pack are
listed in the report (`platforms_without_pack`) instead of silently passing.
`[project] platform` in `.ruttla.toml` forces a pack on in addition.

## Rule engine (Rust)

New rules are data: one TOML file per rule under `src/ruttla/rules/`
([docs/RULE_FORMAT.md](docs/RULE_FORMAT.md)), executed by `ruttla-engine`
(Rust, linear-time `regex` crate, files in parallel). Rules that need parsing
or state across files remain Python checks.

The installer and `ruttla update` put a prebuilt engine next to the `ruttla`
script (Linux x86_64/arm64, macOS arm64/x86_64, Windows x86_64). Without an
engine the declarative rules are reported as *unmeasured*, never as green. On
other platforms build it yourself (Rust ≥ 1.85):

```bash
cargo build --release --locked --manifest-path engine/Cargo.toml
export RUTTLA_ENGINE_BIN="$PWD/engine/target/release/ruttla-engine"   # for a pip install elsewhere
```

`ruttla rule test PATH` checks a rule or rule package before it is merged or
shared: isolated load, fixtures, an untested-exclusion probe, ID clashes and
a runtime budget ([docs/RULE_FORMAT.md](docs/RULE_FORMAT.md)).

A checkout finds its own build without the variable. The engine is never
looked up on `PATH` or in the scanned directory. `--engine required` turns a
missing engine into a runner error (exit 3) — use it in CI.

## Updating

Run `ruttla update` to install the package and the matching engine from the latest GitHub release into the active Python environment — both from the same commit, the engine checked against `SHA256SUMS`. Without a tagged release it takes `nightly`, built from the last green CI run on `main` (`--channel stable|nightly` to choose). This explicit command uses pip and requires network access; ordinary scans remain offline. It does not pull or modify a source checkout.

For an editable clone (`pip install -e .`), update the checkout with `git pull` instead.

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
- **Self-tested rules:** every rule must FAIL on its broken probe and PASS on
  its healthy probe (`ruttla --self-test`); current counts per pack in the
  generated [docs/RULES.md](docs/RULES.md).
- **Evidence-backed catalog:** rules come from real failures, see
  [docs/RULES.md](docs/RULES.md), [docs/GUIDELINES.md](docs/GUIDELINES.md) and
  [LESSONS_LEARNED.md](LESSONS_LEARNED.md).
- **Coverage is visible:** skipped oversize files and platforms without a rule
  pack are reported, not silently dropped.
- **Agent-native output:** stable check IDs, compact agent format, JSON, SARIF.

Packs: universal (brand, i18n, secrets, gates, docs, media, protocol), apple
(incl. App Store release), web, python services, raspberry, godot, unreal,
dotnet (WPF/Avalonia).

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
names APIs that exist. Write it as a TOML rule ([docs/RULE_FORMAT.md](docs/RULE_FORMAT.md))
unless it cannot be expressed as a pattern. Security: [SECURITY.md](SECURITY.md). License: Apache-2.0.
