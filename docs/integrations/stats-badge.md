# Public quality card: badge, history, overview

`ruttla badge` turns full scans into a public card that a project can show in
its README: a current badge, a history badge and a readable summary page. It
is the public counterpart to `ruttla stats`, which never leaves your machine.

## What is published — and what never is

| Published | Never |
|---|---|
| Counts per scan: blocking, advisory, by severity, files scanned | File paths, line numbers, evidence, messages, source code |
| IDs of the rules that ran and how many findings each produced | The scanned root directory |
| Ruttla version, report schema, commit, link to the CI run | Anything from your local `ruttla stats` database |

The card is opt-in per repository: nothing happens until you add the workflow
below. Rule IDs of private packages under `.ruttla/packages/` appear in the
card too — leave the card off if those names are confidential.

## Why the numbers can be checked

- `ruttla badge update` scans by itself and always scans everything. A
  `--changed-only` run would look like "fewer findings".
- Every line of `history.jsonl` names the commit and the Ruttla version, and
  links the CI run. Re-running that version on that commit gives the same counts.
- History starts with the first recorded scan. Nothing is backfilled or
  extrapolated.
- A scan that measured nothing (exit 2) is not added to the history, and the
  badge shows *not measured* instead of the last green state.
- "Fewer findings" is counted only between scans with the same Ruttla version
  and the same rule set. It is never called "fixed": the card cannot see why a
  finding disappeared.

## Workflow: publish on every push to `main`

The card lives on its own branch `ruttla-stats`, so `main` gets no commit noise.
Badges for **public** repositories only: shields.io cannot read raw files of a
private repository.

```yaml
name: ruttla-card

on:
  push:
    branches: [main]

permissions:
  contents: write            # pushes the card to the ruttla-stats branch

concurrency:
  group: ruttla-card
  cancel-in-progress: false  # never drop a history line

jobs:
  card:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - name: Install Ruttla
        run: python -m pip install "git+https://github.com/hehljo/Ruttla@main"
      - name: Check out the card branch
        shell: bash
        run: |
          # Outside the checkout, so the card is not scanned with the project.
          if git fetch -q origin ruttla-stats; then
            git worktree add -B ruttla-stats "$RUNNER_TEMP/card" FETCH_HEAD
          else
            git worktree add --orphan -b ruttla-stats "$RUNNER_TEMP/card"
          fi
      - name: Update the card
        shell: bash
        env:
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
          BADGE_BASE: https://raw.githubusercontent.com/${{ github.repository }}/ruttla-stats
        run: |
          ruttla badge update . --dir "$RUNNER_TEMP/card" --project "$GITHUB_REPOSITORY" --commit "$GITHUB_SHA" --run-url "$RUN_URL" --badge-base "$BADGE_BASE"
      - name: Publish the card
        shell: bash
        working-directory: ${{ runner.temp }}/card
        run: |
          git add -A
          git diff --cached --quiet && exit 0
          git -c user.name="github-actions[bot]" \
              -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
              commit -q -m "Update quality card for ${GITHUB_SHA::7}"
          git push -q origin HEAD:ruttla-stats
```

Exit codes of `ruttla badge`: `0` card written (also when the scan found
something — the badge shows it), `3` scan or card broken (unreadable history,
report missing). The card does not replace the gate: keep the scan step from
[github-actions.md](github-actions.md) for pull requests.

## README badges

Replace `OWNER/REPO`:

```markdown
[![Ruttla](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/OWNER/REPO/ruttla-stats/badge.json)](https://github.com/OWNER/REPO/tree/ruttla-stats)
[![Ruttla history](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/OWNER/REPO/ruttla-stats/badge-history.json)](https://github.com/OWNER/REPO/tree/ruttla-stats)
```

The link opens the `ruttla-stats` branch, where GitHub renders the summary
(`README.md`: current scan, history, trend, rules with fewer findings, and what
the numbers do not say).

## Overview across projects

`ruttla badge combine` adds up several cards into one Markdown table — for
example in the Ruttla repository, from the cards of the projects that publish
one:

```bash
ruttla badge combine card-a card-b --out PROJECTS.md
```

Each argument is a directory with a `status.json`. The table only sums the
cards; the evidence stays in each project's own `history.jsonl`.
