# Code Provenance Audit — 2026-09-24 (P00-T003)

Question: does the repository contain third-party code or text whose license
would conflict with releasing it under Apache-2.0 (ADR-0006)?

## Method

1. Inventory of all tracked files (22 paths at audit time, all text).
2. Search for foreign license markers:
   `copyright|licen[cs]e|spdx|stackoverflow|adapted from|taken from|übernommen aus|kopiert`
   → **no hits** outside the newly added `LICENSE`.
3. Review of module headers and docstrings for copied blocks.
4. Runtime dependency check: the code imports only the Python standard
   library (`tomllib`, `argparse`, `re`, `json`, `subprocess`, …).

## Checklist

| Item | Result |
|---|---|
| Vendored third-party source | none |
| Runtime third-party dependencies | none (stdlib only) |
| Copied snippets with foreign license | none found |
| External documentation | referenced by **URL only** (Apple Developer docs, FFmpeg filter docs, Microsoft PowerShell docs, APScheduler docs, httpx docs, `mount_smbfs(8)`); short quotations of error messages and man-page wording are factual references |
| Apple plist `DOCTYPE` header in fixtures | standard interoperability boilerplate, not creative expression |
| Authorship | single maintainer, with AI coding assistants; no external contributions accepted so far |
| Third-party notices required | **no** |

## Result

No provenance blocker for Apache-2.0. `NOTICE` names the project and the
copyright holder; no third-party attributions are needed. Future
contributions are covered by the inbound=outbound rule in
`CONTRIBUTING.md` (Apache-2.0 §5).
