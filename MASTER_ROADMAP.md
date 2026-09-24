# MASTER ROADMAP — CODE_QUALITY_GENERAL Public & Scale

## Project
CODE_QUALITY_GENERAL → public open-source quality gate

## North Star
Turn real recurring engineering failures into deterministic, local, evidence-backed checks that prevent the same class of mistake from consuming debugging/agent time again.

## Current Phase
P06 — Adoption Controls (P00–P05 umgesetzt 2026-09-24, Repo privat)

## Current Milestone
Public-safe repository baseline ready for architectural migration.

## Next Action
P06-T001 — stable finding fingerprint; P03-T007 performance budget follow-up.

## Blocking Issues
- none for internal work. Public release: sanitized history (P08), trademark check, code-scanning fixture repo (P04-T003).

## Baseline Evidence — 2026-09-24
- 90 registered checks
- 206/206 self-test probes PASS
- 41/41 runner unit tests PASS
- Python 3.13.5 verified locally in analysis environment
- uploaded ZIP SHA-256: `33af3a88ab3c1b7504c175d869ed04ea8ff39b0b7185853f728bdfe5445a8e1b`

## Model Mapping
- Principal: GPT-5.6 Sol — High; xHigh only for hard-to-reverse cross-system decisions if available
- Lead: GPT-5.6 Sol — High
- Worker: fastest reliable coding model — Medium/High
- Independent Reviewer: Claude Opus 5.5 High if available, otherwise strongest available Claude
- Fallback: Gemini 3.8 Flash High


## Evidence Log — 2026-09-24 (Umsetzung P00–P05)

- License Apache-2.0 (ADR-0006), name Ruttla / `ruttla` (ADR-0001, PyPI name free at 404 check)
- Golden projection of the original commit 71b2df4 on 14 pack fixture trees reproduced after every step
- 90 checks / 206 probes unchanged; 99 tests; strict dogfood scan exit 0
- SARIF validated against the OASIS 2.1.0 schema on all fixture trees
- Coverage 87 % (core 86 %), CI floor 86 %
- P03-T007 open: 10k files / 69 MB took 277 s before the regex fix; the fixed
  hotspots are covered by tests/test_performance.py, a fresh budget run is pending
- P04-T003 open: needs a public fixture repo or GitHub Code Security
- Known findings and their prevention: LESSONS_LEARNED.md

---

# P00 — Baseline, Sanitization, Legal & Naming

## Goal
Make the current repository safe to expose without changing its scan semantics.

## Why This Phase Exists
Public visibility is hard to undo. Private names/history, missing license and namespace collisions must be resolved before technical growth.

## Entry Conditions
- current ZIP/repo available
- baseline tests reproducible

## Tasks

- [x] **P00-T001 — Anonymize private project provenance**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Fallback:** Gemini 3.8 Flash High
  - **Reviewer:** Claude Opus 5.5 High
  - **Scope:** replace real private project names, bundle IDs and personally identifying examples with neutral fixture names while preserving technical rationale.
  - **Acceptance criteria:**
    - [ ] grep sweep no longer finds known private names/identifiers
    - [ ] rule behavior unchanged
    - [ ] 206/206 self-tests still pass
  - **Evidence:** pending

- [x] **P00-T002 — Audit Git history for sensitive material**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Fallback:** Claude reviewer for history report
  - **Depends on:** P00-T001
  - **Scope:** secrets, private identifiers, absolute paths, proprietary snippets, generated archives.
  - **Acceptance criteria:**
    - [ ] history report produced
    - [ ] decision: preserve history / rewrite / start sanitized public history
    - [ ] no known secret remains in public history
  - **Evidence:** pending

- [x] **P00-T003 — Code provenance audit**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Reviewer:** human maintainer
  - **Scope:** identify copied/vendor snippets and licensing obligations.
  - **Acceptance criteria:**
    - [ ] provenance checklist complete
    - [ ] third-party notices identified if needed
  - **Evidence:** pending

- [x] **P00-T004 — Decide open-source license**
  - **Owner role:** Maintainer / Principal support
  - **Primary model:** GPT-5.6 Sol High for comparison only
  - **Depends on:** P00-T003, ADR-0006
  - **Scope:** choose Apache-2.0 / MIT / other with explicit human decision.
  - **Acceptance criteria:**
    - [ ] accepted ADR
    - [ ] LICENSE committed
  - **Evidence:** pending

- [x] **P00-T005 — Public naming and namespace check**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Fallback:** Gemini 3.8 Flash High
  - **Scope:** brand/repo, PyPI distribution, module import, CLI binary, GitHub Action identity.
  - **Acceptance criteria:**
    - [ ] PyPI/GitHub/basic trademark collision check
    - [ ] accepted ADR-0001
    - [ ] migration aliases defined if names change
  - **Evidence:** pending

- [x] **P00-T006 — Move/remove maintainer-only autopush behavior from public surface**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Scope:** `autopush.sh` becomes clearly maintainer-only under `scripts/maintainer/` or is omitted from public release.
  - **Acceptance criteria:**
    - [ ] normal contributor flow never auto-commits or auto-pushes
    - [ ] pre-commit/self-test workflow documented separately
  - **Evidence:** pending

- [x] **P00-T007 — Freeze behavioral baseline fixtures**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Scope:** snapshot representative JSON/agent outputs and rule counts before refactor.
  - **Acceptance criteria:**
    - [ ] golden fixtures committed
    - [ ] baseline check count = 90
    - [ ] baseline self-tests = 206
  - **Evidence:** pending

## Exit Gate
- no known sensitive public content
- license accepted
- naming decision made or explicitly blocks release only, not internal refactor
- baseline behavior frozen
- 41/41 unit + 206/206 self-tests green

## Human Validation
Maintainer reviews the exact public README examples and Git history decision.

## Phase Review
Independent reviewer checks sanitization/provenance assumptions without editing.

## Completion Log
Pending.

---

# P01 — Public Contracts & Rule Semantics

## Goal
Define what external users may safely depend on before packaging makes those contracts widely consumable.

## Why This Phase Exists
CLI flags, exit codes, check IDs and JSON become de facto APIs the moment the project is public.

## Entry Conditions
P00 exit gate met.

## Tasks

- [x] **P01-T001 — Accept North Star, V1 scope and non-goals**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** PRODUCT_VISION and REQUIREMENTS accepted; no speculative cloud/LLM/autofix scope in V1.

- [x] **P01-T002 — Formalize exit-code contract**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Scope:** 0/1/2/3 semantics, advisory vs blocking.
  - **Acceptance criteria:** compatibility tests cover all four paths.

- [x] **P01-T003 — Make blocking/advisory explicit in report model**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Depends on:** P01-T002
  - **Acceptance criteria:** additive report fields identify blocking findings without parsing severity/profile heuristically.

- [x] **P01-T004 — Define tool/report/config/rule versioning policy**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Depends on:** ADR-0007
  - **Acceptance criteria:** SemVer + schema compatibility table documented.

- [x] **P01-T005 — Define public rule metadata schema**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Scope:** ID, title, pack, severity, safe default, tags, references, rationale, introduced/deprecated versions.
  - **Acceptance criteria:** current 90 rules can be represented without semantic loss.

- [x] **P01-T006 — Audit all guideline/reference metadata for public usefulness**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Reviewer:** Lead
  - **Depends on:** P01-T005
  - **Acceptance criteria:** internal-only identifiers either mapped to public docs or replaced with public rationale.

- [x] **P01-T007 — Normalize platform registry semantics**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Scope:** resolve `dotnet`, explicit project.platform behavior, CLI platform validation.
  - **Acceptance criteria:** one source of truth for known/detected/supported platforms; tests cover override and no-rule pack cases.

## Exit Gate
Contracts documented and covered by tests; no known accepted-but-unused config field remains.

## Human Validation
Read CLI/report semantics as an external user: can they distinguish „clean“, „advisory findings“, „blocked“, „not measured“, „runner broken“?

## Phase Review
Independent API compatibility review.

## Completion Log
Pending.

---

# P02 — Package Architecture Migration

## Goal
Turn the repo-script into an installable Python package while preserving behavior.

## Why This Phase Exists
Packaging unlocks pipx/uv, GitHub Actions and a stable module boundary; staged migration avoids breaking 90 checks.

## Entry Conditions
P01 contracts accepted.

## Tasks

- [x] **P02-T001 — Add `pyproject.toml` and package metadata**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Depends on:** ADR-0002, ADR-0003, naming decision
  - **Acceptance criteria:** wheel/sdist build; no runtime deps; Python >=3.11.

- [x] **P02-T002 — Introduce `src/` package and CLI entry point**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** installed CLI behaves like `master_gate.py`; `python -m <module>` works.

- [x] **P02-T003 — Keep `master_gate.py` compatibility shim**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Depends on:** P02-T002
  - **Acceptance criteria:** existing invocation still works and passes golden tests.

- [x] **P02-T004 — Split core domain models / config / discovery / git**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Reviewer:** Claude Opus 5.5 High
  - **Acceptance criteria:** no circular imports; behavior parity; core responsibilities documented.

- [x] **P02-T005 — Split CLI / engine / self-test / reporters**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** reporters depend on canonical report model, not runner internals.

- [x] **P02-T006 — Split giant check modules by domain**
  - **Owner role:** Worker + Lead review
  - **Primary model:** GPT-5.6 Sol High for first pack, Worker Medium for mechanical followups
  - **Scope:** Apple, universal, Unreal first.
  - **Acceptance criteria:** stable IDs; same self-test result/count; deterministic import order.

- [x] **P02-T007 — Fix global README/rule-definition exclusion model**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Scope:** rule/test definitions should be excluded by property/context, not globally erase every target `README.md`.
  - **Acceptance criteria:** docs checks can inspect a target README; gate's own rule examples do not self-trigger.

- [x] **P02-T008 — Make skipped-file coverage explicit**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Scope:** size skips/exclusions/relevant unreadable cases represented in diagnostics.
  - **Acceptance criteria:** no relevant max-file skip can produce silent full-green coverage claim.

## Exit Gate
- installable local wheel
- legacy shim parity
- 90 checks, 206 self-probes, 41+ unit tests all green
- golden machine reports equivalent or intentionally versioned

## Human Validation
Install tool into a fresh virtual environment and scan 3 unrelated real repos without repo-local hacks.

## Phase Review
Independent architecture review, no edits.

## Completion Log
Pending.

---

# P03 — Reliability, CI & Performance Foundation

## Goal
Make every change externally reproducible and safe across supported operating systems/Python versions.

## Entry Conditions
P02 package installs locally.

## Tasks

- [x] **P03-T001 — Add GitHub Actions CI matrix**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Scope:** Linux/macOS/Windows; Python 3.11–3.14; 3.15 prerelease compatibility job.
  - **Acceptance criteria:** required core matrix green.

- [x] **P03-T002 — Add package build/install smoke tests**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** fresh wheel install + list/self-test/fixture scan.

- [x] **P03-T003 — Establish coverage baseline and no-regression gate**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** core coverage measured separately; CI floor set to measured baseline, with roadmap to ≥90% core line coverage.

- [x] **P03-T004 — Add fixture repositories per official pack**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** at least one healthy and one failing integration fixture per pack.

- [x] **P03-T005 — Add deterministic output/golden tests**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** stable sort order and machine output escaping tested.

- [x] **P03-T006 — Add performance benchmark harness**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** 1k/10k/50k generated corpus; per-rule timing available to maintainers.

- [ ] **P03-T007 — Measure and accept performance budget**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Depends on:** P03-T006
  - **Acceptance criteria:** PERFORMANCE_BUDGET numbers validated or changed via ADR with data.

- [x] **P03-T008 — Add path/config robustness fuzz/property tests**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** regression suite covers Unicode, separators, path escape variants, malformed config.

## Exit Gate
Cross-platform CI is authoritative; packaging and benchmark baseline are reproducible.

## Human Validation
Contributor can clone on Windows/macOS/Linux and run the documented developer setup without private tooling.

## Completion Log
Pending.

---

# P04 — Standard Reporting & GitHub Integration

## Goal
Make findings first-class in modern CI without coupling scan logic to GitHub.

## Entry Conditions
Canonical report model stable enough from P01/P02.

## Tasks

- [x] **P04-T001 — Implement SARIF 2.1.0 reporter**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Depends on:** ADR-0008
  - **Acceptance criteria:** valid SARIF; stable ruleId = check_id; correct file/line mapping.

- [x] **P04-T002 — Add SARIF schema/golden tests**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** malformed mapping fails tests.

- [ ] **P04-T003 — Validate GitHub Code Scanning upload in public fixture repo**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** at least one intentional fixture alert appears with useful rule help/location.

- [x] **P04-T004 — Add `--version` and structured `--list`**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** JSON rule catalog can be generated from registry metadata.

- [x] **P04-T005 — Add `--explain <check_id>`**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** rationale, references, severity, pack, examples discoverable without opening source.

- [x] **P04-T006 — Publish GitHub workflow integration example**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** copy-paste workflow runs CLI and optionally uploads SARIF with least permissions.

- [x] **P04-T007 — Decide own GitHub Action vs workflow-only for 0.1**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** ADR/decision recorded; avoid premature Marketplace maintenance burden.

## Exit Gate
External users can consume machine findings through JSON and SARIF; GitHub integration proven end-to-end.

## Human Validation
Open a PR in fixture repo and confirm alerts are understandable without reading raw JSON.

## Completion Log
Pending.

---

# P05 — Documentation & Community Launch Surface

## Goal
Make the project usable and contributable by someone who has never seen the private development history.

## Entry Conditions
CLI install/behavior documented and stable enough.

## Tasks

- [x] **P05-T001 — Rewrite public README in English**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Reviewer:** Lead
  - **Acceptance criteria:** install → scan → understand result in <5 minutes.

- [x] **P05-T002 — Keep German docs as translation/secondary entry**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** no two contradictory canonical specs; English contract docs are source of truth.

- [x] **P05-T003 — Add CONTRIBUTING and rule author guide**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** new contributor can add one check with fixtures and run all gates.

- [x] **P05-T004 — Add SECURITY policy and private reporting path**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** supported versions + disclosure process documented.

- [x] **P05-T005 — Add Code of Conduct / CODEOWNERS / PR template**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** GitHub community profile recognizes core files.

- [x] **P05-T006 — Add issue forms for bug/new rule/false positive/false negative**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** issue forms collect reproducible fixtures, versions and consent for anonymized examples.

- [x] **P05-T007 — Generate rule catalog docs from metadata**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** no manually duplicated list of 90+ rules; CI detects stale generated docs.

- [x] **P05-T009 — Add competitor/interoperability section to public docs**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Scope:** explain coexistence with CodeQL/GitHub Code Quality, Ruff, ESLint and platform-specific linters without marketing overclaims.
  - **Acceptance criteria:** README states what this tool does uniquely and when users should prefer existing analyzers.

- [x] **P05-T008 — Add CHANGELOG and release compatibility guide**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium
  - **Acceptance criteria:** users can see new/changed/deprecated rule IDs per release.

## Exit Gate
Repository meets public community baseline; no private context required to install, run, understand or contribute.

## Human Validation
Give README + repo to a fresh tester and observe first install/scan/new-rule attempt.

## Completion Log
Pending.

---

# P06 — Adoption Controls: Baselines, Suppressions & Profiles

## Goal
Allow noisy legacy repositories to adopt the gate without disabling useful rules globally.

## Why This Phase Exists
Public users will have existing debt. Without precise suppression, they choose between thousands of findings and turning checks off.

## Entry Conditions
Public report model and stable IDs from P01–P04.

## Tasks

- [ ] **P06-T001 — Design stable finding fingerprint**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Reviewer:** Claude Opus 5.5 High
  - **Acceptance criteria:** line movement does not trivially invalidate fingerprint; collisions/renames considered.

- [ ] **P06-T002 — Implement baseline file format**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Depends on:** P06-T001
  - **Acceptance criteria:** known findings suppressed, new findings remain visible; baseline diff inspectable.

- [ ] **P06-T003 — Implement scoped suppression with reason/expiry**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** check/file/fingerprint scope; suppression without reason rejected or warned by policy.

- [ ] **P06-T004 — Add profile presets without hiding coverage**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Scope:** e.g. `recommended`, `strict`, pack-specific.
  - **Acceptance criteria:** report always states active profile and disabled rule count.

- [ ] **P06-T005 — Add baseline migration/version tests**
  - **Owner role:** Worker
  - **Primary model:** GPT-5.6 Sol Medium

## Exit Gate
Legacy repo can establish a transparent baseline and block only net-new errors.

## Human Validation
Adopt on a deliberately noisy real repository without mass `off` configuration.

## Completion Log
Pending.

---

# P07 — Rule Catalog Expansion & Pack Architecture

## Goal
Grow beyond the initial 90 checks without turning the core into an unreviewable regex dump.

## Entry Conditions
Contribution protocol, generated docs and CI are live.

## Tasks

- [ ] **P07-T001 — Define official pack taxonomy**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** universal, ci/github, python, web/node, apple, godot, unreal, raspberry, media, docker, dotnet boundaries documented.

- [ ] **P07-T002 — Add CI/GitHub pack from real failure evidence**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** only evidence-backed rules; Action security/exit-code mistakes prioritized.

- [ ] **P07-T003 — Expand Python packaging/service pack**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** public-source rationale and fixtures for each added rule.

- [ ] **P07-T004 — Add Docker/container pack**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Entry condition:** at least one real/reproduced high-value failure set.

- [ ] **P07-T005 — Implement first .NET pack or remove unsupported platform promise**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** platform registry cannot claim a pack that does not exist.

- [ ] **P07-T006 — Define external plugin API v0**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High
  - **Reviewer:** Claude Opus 5.5 High
  - **Depends on:** ADR-0005
  - **Acceptance criteria:** API version, entry-point group, trust warning, compatibility tests.

- [ ] **P07-T007 — Build official-plugin conformance test kit**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** third-party pack can run contract tests outside core repo.

## Exit Gate
Catalog growth is modular, documented, testable and does not require editing monolithic files.

## Human Validation
External contributor builds one small experimental pack from template.

## Completion Log
Pending.

---

# P08 — Public Beta 0.1.0 Release

## Goal
Publish a credible, safe first public release.

## Entry Conditions
P00–P05 complete. P06/P07 can continue after beta unless required by validation.

## Tasks

- [ ] **P08-T001 — Final privacy/license/provenance audit**
  - **Owner role:** Independent Reviewer
  - **Primary model:** Claude Opus 5.5 High
  - **Mode:** READ / ANALYZE / REPORT / DO NOT EDIT
  - **Acceptance criteria:** no blocker findings.

- [ ] **P08-T002 — Final release candidate matrix**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** all required OS/Python/packaging/SARIF jobs green.

- [ ] **P08-T003 — Configure PyPI Trusted Publishing**
  - **Owner role:** Maintainer + Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** no long-lived PyPI token in repo secrets; dedicated release workflow.

- [ ] **P08-T004 — Publish `0.1.0` release candidate**
  - **Owner role:** Maintainer
  - **Acceptance criteria:** TestPyPI or equivalent smoke path successful.

- [ ] **P08-T005 — Publish GitHub + PyPI 0.1.0**
  - **Owner role:** Maintainer
  - **Acceptance criteria:** install from public package; self-test + sample scan pass.

- [ ] **P08-T006 — Post-release smoke from clean Linux/macOS/Windows environments**
  - **Owner role:** Lead
  - **Primary model:** GPT-5.6 Sol High
  - **Acceptance criteria:** no local-repo assumptions.

- [ ] **P08-T007 — Open public roadmap/discussions**
  - **Owner role:** Maintainer
  - **Acceptance criteria:** clear issue labels and contribution path live.

## Exit Gate
0.1.0 is publicly installable, documented, auditable and reproducible.

## Human Validation
A user with no project history successfully installs and runs it on their own repo.

## Completion Log
Pending.

---

# P09 — Ecosystem Growth & 1.0 Stabilization

## Goal
Turn early public feedback into stable contracts and a maintainable ecosystem.

## Entry Conditions
At least one 0.x release used externally.

## Tasks

- [ ] **P09-T001 — Track false-positive/false-negative metrics manually from issues**
  - **Owner role:** Maintainer
  - **Note:** no telemetry required.

- [ ] **P09-T002 — Complete one deprecation cycle**
  - **Owner role:** Lead
  - **Purpose:** prove Rule-ID/versioning policy works before 1.0.

- [ ] **P09-T003 — Validate third-party plugin boundary in practice**
  - **Owner role:** Principal
  - **Primary model:** GPT-5.6 Sol High

- [ ] **P09-T004 — Decide Homebrew/winget/choco distribution based on demand**
  - **Owner role:** Maintainer
  - **Rule:** do not add release burden without usage evidence.

- [ ] **P09-T005 — Establish pack code owners / second release maintainer**
  - **Owner role:** Maintainer
  - **Entry condition:** contributor base exists.

- [ ] **P09-T006 — 1.0 compatibility audit**
  - **Owner role:** Independent Reviewer
  - **Primary model:** Claude Opus 5.5 High
  - **Acceptance criteria:** CLI, config, JSON, SARIF, rule lifecycle, security and release contracts ready to freeze.

- [ ] **P09-T007 — Release 1.0.0**
  - **Owner role:** Maintainer
  - **Depends on:** P09-T006

## Exit Gate
1.0 contracts can be maintained without frequent breaking changes.

## Human Validation
At least one external contributor and one external adopter confirm workflows without private maintainer assistance.

## Completion Log
Pending.

---

# Cross-Phase Definition of Done

A task marked `[x]` requires:

- acceptance criteria met
- relevant tests added/updated and green
- self-test count/result checked
- build/package checked where relevant
- docs updated
- no unrelated refactor
- final diff reviewed
- limitations recorded
- evidence appended to task/phase log

# Final Product Validation Questions

Before calling the public transformation complete:

- Can a fresh user install it in one normal Python-tool command?
- Can they understand Exit 0/1/2/3 without reading source?
- Can they inspect why a rule exists?
- Can they report a false positive reproducibly?
- Can a contributor add a rule without touching core runner code?
- Can GitHub display findings natively through SARIF?
- Can a legacy repo adopt it without disabling everything?
- Does a scan remain local, offline and non-executing?
- Can an agent resume development from repo docs alone?
