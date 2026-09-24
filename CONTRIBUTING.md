# Contributing to Ruttla

Contributions are accepted under the Apache-2.0 license (inbound = outbound,
Apache-2.0 §5). No CLA.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[dev]"
git config core.hooksPath .githooks        # optional: self-test before commit
```

## Gates every change must pass (what CI runs)

```bash
python -m unittest discover -s tests       # unit, contract, golden, provenance, fuzz
python master_gate.py --self-test          # every rule: broken FAILS, healthy PASSES
python scripts/gen_rule_docs.py --check    # docs/RULES.md is generated
ruff check .
python master_gate.py . --strict           # Ruttla scans itself
```

Never pipe a gate before reading its status (`cmd | tail` reports `tail`).

## Adding a rule — evidence first

A rule is mergeable only with:

1. a real or minimally reproduced failure (exact error text);
2. the proven cause (documentation, not memory);
3. a check whether an **existing** rule should have caught it, and why not;
4. a broken probe that FAILS and a healthy probe that PASSES
   (`SelfTestCase` in the `@register` call); hard rules also need the most
   likely false positive as a healthy probe;
5. a false-positive analysis; `safe_by_default=True` only if a false positive
   is impossible;
6. a `fix` text that names only APIs that exist (checked against docs);
7. version thresholds as named constants with their measurement;
8. a CHANGELOG entry; `python scripts/gen_rule_docs.py`.

Place the rule in `src/ruttla/checks/<pack>/<topic>.py` and import from
`ruttla.core`. Shared helpers go into `_*.py` modules (not loaded as rules).
Measure the **property**, not the code shape; count candidates, not only
violations, so a healthy project reports `pass`, not `unmeasured`.

Public text never names private projects: write "observed in a real macOS
App Store submission", not the project name (`tests/test_provenance.py`).

## Check IDs

IDs are public contracts: never rename for wording; new semantics = new ID +
deprecation of the old one. The frozen list is `tests/golden/check_ids.txt`.

## Issues

Use the issue forms: bug, new real-world failure, false positive, false negative.
