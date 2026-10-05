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
| `[match] message` | yes | `{N}` = group N, `{N:L}` = `snippet(group, L)`, `{{`/`}}` = literal braces. Unknown groups are rejected |
| `[match] fix` | no | Naming an API (`Name(`, `Type.member(` or backticks) requires `references` |
| `[match] guideline` | no | Guideline in the finding, if it differs from the catalogue one |
| `[[match.exclude]]` | no | Drop a hit: `on = "match"` (default; `group = N` selects a group), `"line"` (trimmed raw line) or `"path"` (relative path; the file still counts as examined) |
| `[[fixtures]]` | yes | `name`, `expect` (`pass`/`fail`/`unmeasured`/`error`), optional `expect_finding_contains`, `[fixtures.files]` path → content. At least one `fail` **and** one `pass` |

Findings carry `file`, `line` (of the match start), `evidence` =
`snippet(trimmed raw line)`, `message`, `fix`, `guideline`. Status: no
examined file → `unmeasured`; hits → `fail`; else `pass`. Fixtures run like
`ruttla --self-test`: files in an empty directory, unscoped view; with
`expect_finding_contains` the text must occur in `message + " " + evidence`
of some finding.

## Port of a Python check (P11-T008)

1. `python3 scripts/port_rule.py CHECK_ID` — skeleton with all metadata and
   the check's self-test probes as fixtures (unchanged: they are the oracle).
2. Fill `[scope]` and `[match]` from the Python source quoted in the
   skeleton, then delete that comment block. Lookaround becomes an
   `exclude` entry or stays in Python (then the check is not portable in v0).
3. `engine/target/debug/ruttla-engine selftest --rules src/ruttla/rules --rule CHECK_ID`
   → every fixture `ok`.
4. `python3 scripts/engine_diff.py findings --check CHECK_ID` — the Python
   check (still present, rule is *shadowed*) against the rule over the
   reference corpus. Must end with exit 0 and `N/N Repos identisch`.
5. Delete the Python check (decorator, function, now unused helpers/imports).
6. `python3 master_gate.py --self-test` — probe count unchanged, green;
   `python3 scripts/engine_gate.py`; `python3 -m unittest discover -s tests`;
   `python3 scripts/gen_rule_docs.py --check`.

Never commit a state where a rule and a Python check share an ID
(`tests/test_engine_declarative.py` fails on it).
