# Git History Audit — 2026-09-24 (P00-T002)

Scope: every commit reachable from any ref at the time of the audit
(6 commits, `e9c4c48` … `71b2df4`, 2026-09-18 → 2026-09-23).

This report deliberately does **not** repeat the private identifiers it
found. It names categories and counts only; the hashed deny-list in
`tests/test_provenance.py` keeps them out of the working tree.

## Method

```bash
git log --all --name-only --format=      # every path ever committed
git log --all --numstat --format=        # binary / archive blobs
git log --all -p | grep '^+' | grep -E <secret patterns>
git log --all -p | grep '^+' | grep -E <absolute path patterns>
git show <commit> | grep -ciE <private project names>   # per commit
git log --all --format='%an <%ae> / %cn <%ce>'
```

Secret patterns: GitHub tokens (`ghp_…`), OpenAI-style keys (`sk-…`), AWS
access keys (`AKIA…`), PEM private keys, Slack tokens, Google API keys,
Telegram bot tokens (`<digits>:<35 chars>`).

## Findings

| Category | Result | Severity for a public release |
|---|---|---|
| Secrets / credentials | **none found** | — |
| Binary blobs / generated archives | **none** (22 text paths only) | — |
| Private project names | present in **all 6 commits** (1–29 hits per commit): app names, a game project name, a trading-bot name, a web-app name, a brand used as README example | **blocker** |
| Real bundle identifier (personal reverse-DNS prefix) | present in history | **blocker** |
| Probable real Apple Developer Team ID in a self-test fixture | present in history (1 commit) | **blocker** |
| Absolute maintainer path (`/root/<private project>`) | 1 occurrence in history | minor |
| Author / committer metadata | personal e-mail address on all 6 commits | **blocker** for public history unless intended |
| AI-assistant trailer in an auto-commit script | present in history | cosmetic |

All working-tree occurrences were removed in P00-T001 (see
`CHANGELOG.md`). The golden baseline in `tests/golden/` proves the
anonymisation did not change rule behaviour.

## Decision

| Option | Assessment |
|---|---|
| Preserve history as-is when going public | **rejected** — leaks private names, bundle ID, team ID and personal e-mail |
| Rewrite history (`git filter-repo` with replace-text + mailmap) | possible, but every existing clone/fork keeps the old objects; error-prone for a 6-commit history |
| **Start a sanitized public history** | **recommended** — squash the sanitized tree into a fresh root commit with a no-reply author address when visibility changes to public |

The repository **stays private** (maintainer decision 2026-09-24). No history
rewrite is performed now. The decision above becomes an entry condition of
P08-T001 (final privacy audit) before any visibility change.

## Checklist before visibility = public

- [ ] fresh root commit from the sanitized tree (or filter-repo rewrite)
- [ ] author e-mail set to the GitHub no-reply address
- [ ] `python -m unittest tests.test_provenance` green on the new history
- [ ] re-run the secret-pattern scan above on the new history
- [ ] old private repository archived, not made public
