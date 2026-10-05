# Declarative rule format `ruttla-rule/0`

Status: v0 (P10-T008, ADR-0011). One rule = one TOML file at
`src/ruttla/rules/<platform>/<id>.toml`. Rules are **data**: no executable
code. `ruttla-engine` (Rust, `regex` crate, linear time) executes them;
Python reads only catalogue metadata and fixtures. Without the engine a rule
is *not measured* — never green (`--engine auto|off|required`).

## Fields

| Key | Required | Meaning |
|---|---|---|
| `format` | yes | `"ruttla-rule/0"` |
| `id` | yes | `namespace.name`; must equal the file name without `.toml` |
| `title`, `platform`, `severity` | yes | `platform` from `platforms.toml`; `severity` = `error`/`warning`/`info` |
| `guideline`, `rationale`, `tags`, `references`, `safe_by_default`, `introduced_in`, `lifecycle` | no | Catalogue metadata, same meaning as `register()` |
| `[scope] extensions` | yes | Lower-case, with dot. One examined unit = one file of these extensions in the platform's view |
| `[scope] unit_label` | yes | e.g. `"GDScript-Dateien"` |
| `[scope] no_files_reason` | no | Reason when no file was examined (default: `Null <label> geprüft — es gab nichts zu messen.`) |
| `[scope] skip_comments` | no | Default `true`: match on comment-stripped text (`strip_comments`, lines preserved) |
| `[scope] include_rule_files` | no | Default `false`: files that define checks/tests are skipped, as in `ctx.files()` |
| `[scope] require_text` | no | Literal; files without it are not examined (and not counted) |
| `[match] pattern` | yes | `regex`-crate syntax. Lookaround and backreferences are rejected at load; a pattern matching the empty text too |
| `[match] per_line` | no | Default `false`: one pass over the whole file, every hit (Python `iter_matches`/`finditer`). `true`: the pattern runs on each `str.splitlines()` line, at most one hit per line (Python `for line in sf.lines: pat.search(line)`); lines are counted at every `splitlines` separator, not only `\n`. `\A`/`\z` are rejected — write `^`/`$` |
| `[match] message` | yes | `{N}` = group N, `{N:L}` = `snippet(group, L)`, `{{`/`}}` = literal braces. Unknown groups are rejected |
| `[match] fix` | no | Naming an API (`Name(`, `Type.member(` or backticks) requires `references` |
| `[match] guideline` | no | Guideline in the finding, if it differs from the catalogue one |
| `[[match.exclude]]` | no | Drop a hit: `on = "match"` (default; `group = N` selects a group), `"line"` (trimmed raw line) or `"path"` (relative path; the file still counts as examined) |
| `[[fixtures]]` | yes | `name`, `expect` (`pass`/`fail`/`unmeasured`/`error`), optional `expect_finding_contains`, optional `expect_findings` (exact number of findings), `[fixtures.files]` path → content. At least one `fail` **and** one `pass` |

Findings carry `file`, `line` (of the match start), `evidence` =
`snippet(trimmed raw line)`, `message`, `fix`, `guideline`. Status: no
examined file → `unmeasured`; hits → `fail`; else `pass`. Fixtures run like
`ruttla --self-test`: files in an empty directory, unscoped view; with
`expect_finding_contains` the text must occur in `message + " " + evidence`
of some finding.

## Conformance kit: `ruttla rule test PATH…` (P10-T009)

Checks a rule file or a package (directory, all `*.toml`) the way the hub will
before admission. Needs only the installed package and engine, not this repo.
Every rule is loaded **in isolation** (own copy in an empty directory). Steps,
each reported on its own — one rejection never hides another:

| Step | Rejects |
|---|---|
| `schema` | everything `ruttla-engine check-rules` rejects: lookaround/backreferences (the classic ReDoS shapes), patterns over the `regex` size limit, missing `fail`/`pass` fixture, `fix` naming an API without `references`, … |
| `id` | an ID of an official check (unless the file *is* that official rule, byte for byte) or a duplicate ID within the package |
| `fixtures` | any fixture that does not hold |
| `wirksamkeit` | fixtures that stay green when the pattern is neutralized, or when any single `[[match.exclude]]` is removed — such an exclusion is an untested exemption. Add a `pass` fixture per exclusion |
| `budget` | scan of three ~1 MB stress files (content of the `pass` fixtures repeated, the same as one line, blank lines) over 10 s, or engine output over 64 MB (finding flood) |

Exit 0 = all accepted, 1 = at least one rejected, 2 = not measured (no
engine), 3 = usage error or no rule found. `--format json` emits
`ruttla-rulekit/0`. Nested quantifiers such as `^(a+)+$` are accepted: the
`regex` crate is linear, the budget step measures it instead of guessing from
the pattern's shape.

## Port of a Python check (P11-T008)

1. `python3 scripts/port_rule.py CHECK_ID` — skeleton with all metadata and
   the check's self-test probes as fixtures (unchanged: they are the oracle).
2. Fill `[scope]` and `[match]` from the Python source quoted in the
   skeleton, then delete that comment block. `per_line` follows the loop
   shape of the source, never the pattern: a per-line `search` ported as a
   whole-file pattern lets `\s` cross line breaks, reports two hits on one
   line and misses lines split at `\f`/`\v`/U+2028 — a corpus without those
   cases still says "identical". Such ports get fixtures for all three, with
   `expect_findings`. Lookaround becomes an
   `exclude` entry or stays in Python (then the check is not portable in v0).
3. `engine/target/debug/ruttla-engine selftest --rules src/ruttla/rules --rule CHECK_ID`
   → every fixture `ok`.
4. `python3 scripts/engine_diff.py findings --check CHECK_ID` — the Python
   check (still present, rule is *shadowed*) against the rule over the
   reference corpus. Must end with exit 0 and `N/N Repos identisch`.
5. Delete the Python check (decorator, function, now unused helpers/imports).
6. `ruttla rule test src/ruttla/rules/<platform>/CHECK_ID.toml` — accepted;
   `python3 master_gate.py --self-test` — probe count unchanged, green;
   `python3 scripts/engine_gate.py`; `python3 -m unittest discover -s tests`;
   `python3 scripts/gen_rule_docs.py --check`.

Never commit a state where a rule and a Python check share an ID
(`tests/test_engine_declarative.py` fails on it).

## Hub packages: `ruttla hub` (P10-T010)

Community rules come as packages from the index repo `ruttla-hub` (GitHub
releases, direct download URLs, no API). A package is one canonical JSON
document `ruttla-hub-package/0` (`name`, `version`, `description`, `evidence`
= https URLs to the observed failure, `license`, `rules` = path → rule text).
Rule IDs must live in `hub.<package>.` — a clash with an official check or
another package is impossible by construction; the engine still aborts on a
duplicate ID across `--rules` directories.

| Command | Network | Effect |
|---|---|---|
| `ruttla hub search [TEXT]` | yes | list the index |
| `ruttla hub add NAME` | yes | download, check sha256 against the index, verify the Sigstore bundle (identity: the index repo's `publish.yml` on `main`), write `.ruttla/hub/NAME/package.json` and `ruttla-hub.lock` |
| `ruttla hub sync` | only for missing/changed packages | restore exactly the locked versions, same checks |
| `ruttla hub remove NAME` | no | drop from lock and store |
| `ruttla hub check DIR --corpus DIR…` | no | admission (index CI): format · conformance kit · false-positive scan over the healthy corpus (threshold 0; a rule that examines no corpus file is *not measured*) |
| `ruttla hub build PACKAGES OUT [--previous index.json]` | no | canonical package files + `index.json`; a published version with different content aborts, so does a version older than the published one |

`add`/`sync` need `sigstore` (`pip install 'ruttla[hub]'`); without it they
abort — nothing is installed unverified. A scan loads locked packages offline
and only when the stored bytes match the lockfile hash; a mismatch or a missing
package is a runner error (exit 3, `hub_lock_mismatch`). `.ruttla/` is excluded
from scans. The lockfile guards against corruption and hand edits, not against
a malicious target repo — whoever writes the repo writes the lockfile too; the
design bounds the damage (data only, linear-time patterns, additional findings
only).
