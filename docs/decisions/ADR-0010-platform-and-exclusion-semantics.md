# ADR-0010 — Platform selection and exclusion semantics

## Status
Accepted — 2026-09-24 (P01-T007, P02-T007)

## Decisions
1. `project.platform` **adds** a rule pack to detection; it never removes one,
   so a profile cannot shrink coverage silently.
2. Platforms without a rule pack (`dotnet`) are detected and reported
   (`platforms_without_pack`), but rejected in `project.platform` and
   `--platform`, because the value would have no effect.
3. Only agent-instruction files and gate profiles are excluded by name
   (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `HANDOVER.md`, `ROADMAP.md`,
   `MASTER_ROADMAP.md`, profiles). `README.md` / `CHANGELOG.md` are measured.
   Rule documentation opts out by property: `<!-- ruttla:rule-docs -->`.
4. Profile `exclude` globs apply to every directory lookup, including
   platform detection.
