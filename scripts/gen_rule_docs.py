#!/usr/bin/env python3
"""Regenerate docs/RULES.md from the rule registry (P05-T007).

    python scripts/gen_rule_docs.py          # write docs/RULES.md
    python scripts/gen_rule_docs.py --check  # exit 1 if the file is stale (CI)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ruttla.catalog import rules_markdown  # noqa: E402
from ruttla.engine import load_checks  # noqa: E402

TARGET = REPO / "docs" / "RULES.md"


def main(argv: list[str]) -> int:
    load_checks()
    text = rules_markdown()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print("docs/RULES.md is stale — run: python scripts/gen_rule_docs.py", file=sys.stderr)
            return 1
        print("docs/RULES.md is up to date.")
        return 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
