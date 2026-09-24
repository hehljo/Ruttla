## What and why

## Evidence (new or changed rule)
- [ ] real or minimal failure reproduced (error text):
- [ ] cause proven with documentation (link):
- [ ] existing rule checked — why it did not catch this:
- [ ] broken probe FAILS, healthy probe PASSES (`--self-test` count went up)
- [ ] false-positive analysis; `safe_by_default` justified or false
- [ ] fix text names only existing APIs

## Gates
- [ ] `python -m unittest discover -s tests`
- [ ] `python master_gate.py --self-test`
- [ ] `python scripts/gen_rule_docs.py --check`
- [ ] CHANGELOG.md updated; no check ID renamed or removed
