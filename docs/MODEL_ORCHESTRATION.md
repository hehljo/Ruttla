# MODEL ORCHESTRATION

Stand: 2026-09-24. Modelle vor größerer Phase erneut prüfen.

## Stable Roles

### Principal Architect
Use for:
- package/API boundaries
- plugin trust model
- schema/versioning
- breaking changes
- license/naming implications only as analysis, human decides final legal/business choice

Default: GPT-5.6 Sol High.
Independent challenge: strongest available Claude, currently Opus 5.5 if available.

### Lead Implementer
Use for:
- staged core split
- SARIF reporter
- packaging
- CI/release
- complex compatibility work

Default: GPT-5.6 Sol High.

### Worker
Use for:
- docs
- isolated rule modules
- fixtures
- issue templates
- mechanical module moves after architecture is fixed

Default: fastest reliable available coding model at Medium.

### Independent Reviewer
Use READ/ANALYZE/REPORT, no edits by default.

Default: Claude Opus 5.5 High if available; otherwise strongest available Claude.

### Alternate/Fallback
Gemini 3.8 Flash High for:
- independent bug reproduction
- broad static review
- second implementation experiment
- quota/provider fallback

## Task Assignment Rules

- P00 privacy/source scrub: Lead High + Reviewer
- P01 contracts/ADRs: Principal High
- P02 package refactor: Lead High, Principal for boundaries
- P03 tests/CI: Lead High + Worker Medium
- P04 SARIF/integrations: Lead High + Reviewer
- P05 public docs/community: Worker Medium, Lead review
- P06 baseline/plugin work: Principal High/xHigh + Reviewer
- new isolated rule: Worker High if clear; Lead High if parser/stateful
- release audit: Independent Reviewer High

## Escalation

Two serious failures at same tier → stop, capture exact state, root-cause analysis, then escalate.

## Parallel Worktree Policy

One agent per worktree:

```text
main
├── refactor/core-package
├── feat/sarif
├── docs/public
└── fix/platform-detection
```

No two agents edit the same working tree concurrently.
