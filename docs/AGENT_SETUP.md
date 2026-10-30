# Agent setup — one prompt for any coding agent

Copy the block under **Prompt** into the session of your coding agent (Codex,
Claude Code, Cursor, Copilot, Aider, …) in the project you want to guard. Copy
the block under **Project snippet** into that project's `AGENTS.md`,
`CLAUDE.md`, `.cursor/rules` or equivalent, so every later session follows it
without the prompt.

Every command and option in this file is checked against the real CLI by
`tests/test_agent_setup.py`; a renamed option turns that test red instead of
leaving a stale prompt behind.

## Prompt

````text
Set up Ruttla, a deterministic offline quality gate, in this project and use it
from now on. Follow these steps exactly.

1. Install (once per machine, skip if `ruttla --version` already works):
     Linux/macOS:  curl -fsSL https://raw.githubusercontent.com/hehljo/Ruttla/main/install.sh | sh
     Windows:      irm https://raw.githubusercontent.com/hehljo/Ruttla/main/install.ps1 | iex
   Then verify package and Rust engine:
     ruttla --version
     ruttla --self-test --engine required
   Exit 0 = installed and healthy. Anything else: report the output to the user
   and stop — without the engine, declarative rules are "unmeasured", not green.
   Later updates only when the user asks: `ruttla update`.

2. Gate at the end of every task (before you report "done" or commit):
     out=$(ruttla . --format agent); status=$?
   Read the status BEFORE filtering the output — never pipe the gate itself
   (`ruttla . | tail` reports tail's status). Meaning:
     0  measured, no blocking finding (advisory findings may still be listed)
     1  blocking finding — fix it, then run the gate again
     2  nothing was measured — this is NOT a pass; say so to the user
     3  runner/config/input error — report it, do not retry blindly
   Lines starting with UNMEASURED, NO_PACK, SKIPPED or BROKEN_LINK are parts
   that were not checked. Name them in your report; never call them green.
   On larger repositories, `ruttla . --changed-only --format agent` checks only
   changed and untracked files; it says nothing about the rest.
   To understand a rule: `ruttla --explain CHECK_ID`. Rule catalogue: `ruttla --list`.

3. When the user reports a bug (build error, crash, wrong behaviour) that a
   pattern could have caught, the main deliverable is a RULE, not only the fix:
   - write a TOML rule `ruttla-rule/0` under
     .ruttla/packages/NAME/rules/<platform>/hub.NAME.<rule>.toml
     next to .ruttla/packages/NAME/package.toml (format: docs/RULE_FORMAT.md in
     the Ruttla repository), with at least one `fail` and one `pass` fixture;
   - check it:  ruttla rule test .ruttla/packages/NAME
     (exit 0 = accepted, 1 = rejected, 2 = no engine, 3 = usage error);
   - run the gate on the broken state (must report the finding) and on the
     fixed state (must not). Local packages run in every scan; no update or
     hub command overwrites them.

4. Never without the user's explicit consent in this conversation:
   - `ruttla hub submit NAME --yes` (publishes the rule as a pull request to
     the public community index). Without `--yes` it only shows the plan; you
     may run that and show it to the user.
   - `ruttla stats enable` (local usage statistics, off by default). Do not
     enable, disable or delete statistics on your own.
   - `ruttla update`, `ruttla hub add NAME`, `ruttla hub sync`, or a scan with
     `--allow-network` (these use the network; ordinary scans are offline).

5. Report briefly: exit code, number of blocking findings, what was not
   measured, and any rule you added.
````

## Project snippet

````markdown
## Quality gate (Ruttla)

- At the end of every task: `out=$(ruttla . --format agent); status=$?` —
  read the status before filtering. 0 = pass, 1 = blocking finding (fix and
  rerun), 2 = nothing measured (not a pass), 3 = runner error (report).
- UNMEASURED / NO_PACK / SKIPPED lines are unchecked parts: name them, never
  call them green.
- A reported bug that a pattern could have caught becomes a rule under
  `.ruttla/packages/NAME/`, checked with `ruttla rule test .ruttla/packages/NAME`.
- Never without explicit consent: `ruttla hub submit NAME --yes`,
  `ruttla stats enable`, `ruttla update`, network options.
````

## Why these rules

| Rule | Reason |
|---|---|
| Status before filtering | A pipe returns the status of its last command; a red gate then looks green. |
| Exit 2 is not green | "0 of 0 files clean" is trivially true. Ruttla separates *measured and clean* from *nothing measured*. |
| A bug becomes a rule | The fix repairs one place; the rule catches the same mistake in every later change and project, without spending tokens. |
| `--engine required` once at setup | Without the engine the declarative rules report *unmeasured*; the self-test makes that a hard error instead. |
| Consent for `hub submit` and `stats enable` | One publishes to a public repository, the other starts recording on the user's machine. Both are the user's decision. |
