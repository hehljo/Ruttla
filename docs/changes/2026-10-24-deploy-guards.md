# Additive deployment guards — 2026-10-24

Change class: minor (three new checks and an optional declarative scope field).
Existing check IDs, report schema and CLI exit-code contracts remain unchanged.

- Add blocking `web.capacitor_app_start_path_spa_route` for conventional SPA
  routes used as a bundled Capacitor start file, with 12 TOML fixtures.
- Add blocking `repo.git_hook_not_executable` for indexed Git hooks at 100644,
  with candidate counts, unknown boundaries and real Git metadata fixtures.
- Add warning `web.netlify_cli_deploy_without_site` for executable deploy
  commands without an explicit target; parse JSON scripts and shell arguments.
- Add optional `scope.file_names` (literal basename AND extension selection).
  The rule conformance budget preserves these filenames in its stress corpus.
- Extend the trusted self-test harness with a data-only Git index declaration;
  the frozen export field sets and ordinary scanner input remain unchanged.

Rule rationale, healthy/defective controls, false-positive boundaries and
primary references: [deployment safety checks](../rules/deployment-safety.md).

This separate change record deliberately leaves the concurrently edited root
CHANGELOG, STATUS and generated RULES catalogue untouched. The generated
catalogue must be refreshed in a separately authorized integration step.
