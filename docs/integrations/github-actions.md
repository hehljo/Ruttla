# GitHub Actions integration (P04-T006)

Decision for 0.1 (ADR-0009): **workflow-only**. Ruttla ships no own
Marketplace Action yet; a plain workflow step is enough and avoids a second
release artefact.

## Copy-paste workflow

```yaml
name: ruttla

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read            # the scan only reads the checkout

jobs:
  ruttla:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write   # only needed for the SARIF upload step
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - name: Install Ruttla
        # Pin an exact commit until 0.1.0 is on PyPI. Never install an
        # unpublished name from PyPI: anyone could register it first.
        run: python -m pip install "ruttla @ git+https://github.com/OWNER/REPO@COMMIT_SHA"
      - name: Scan
        shell: bash
        run: |
          # Capture the status BEFORE filtering: `ruttla | tee` reports tee's status.
          set +e
          ruttla . --format agent --sarif ruttla.sarif > ruttla.txt
          status=$?
          set -e
          cat ruttla.txt
          echo "status=$status" >> "$GITHUB_OUTPUT"
          exit 0            # decide below, after the upload
        id: scan
      - name: Upload findings to code scanning
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: ruttla.sarif
          category: ruttla
      - name: Enforce the gate
        shell: bash
        run: |
          case "${{ steps.scan.outputs.status }}" in
            0) echo "green";;
            1) echo "blocking findings"; exit 1;;
            2) echo "NOTHING was measured — not a success"; exit 1;;
            *) echo "runner error"; exit 1;;
          esac
```

## Notes

- **Exit 2 is red.** A run that measured nothing is not a pass. Treat it like
  a failure unless the repository genuinely has nothing Ruttla can check.
- **Every SARIF result has a location.** GitHub rejects an upload if any
  result lacks one; project-level findings are anchored on the profile,
  `README.md` or the first scanned file and carry
  `properties.projectLevel = true`.
- **Private repositories** need GitHub Advanced Security / Code Security for
  code-scanning uploads. Without it, drop the upload step and keep the
  agent/text output and the exit code.
- **Pull requests from forks** get a read-only token; the upload step is then
  skipped by GitHub. The enforce step still works.
- **Changed files only:** `ruttla . --changed-only origin/main` scans only what
  the branch changed (tracked and untracked). Fetch enough history
  (`fetch-depth: 0`) for the base ref to exist.
- **Coexistence:** Ruttla complements CodeQL / GitHub Code Quality, Ruff,
  ESLint and SwiftLint — upload each tool's SARIF under its own `category`.
