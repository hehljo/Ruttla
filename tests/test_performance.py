"""Regression guards from the performance baseline (P03-T006/T007).

Finding (2026-09-24): after `strip_comments`, a comment block becomes lines
of spaces. MULTILINE patterns starting with `^\\s*` then (a) backtracked over
the whole whitespace block from every line start — quadratic, 98 s for one
rule on a 69 MB corpus — and (b) could start their match on an earlier blank
line, so the reported line pointed at the top of the comment block instead of
the declaration. `^[ \\t]*` expresses the intent (indentation only).
"""

from __future__ import annotations

import time
import unittest

from _support import cli_json, ensure_checks_loaded, make_tree

from ruttla.config import Config
from ruttla.context import Context
from ruttla.registry import REGISTRY

AFFECTED = [
    "apple.mainactor_missing_on_observable",
    "godot.balance_value_in_code",
    "python.telegram_token_log_leak",
    "protocol.version_bump_without_fallback",
    "protocol.ui_named_runtime_term",
    "rpi.no_restart_policy",
]


class CommentBlockTests(unittest.TestCase):
    def test_line_number_points_at_declaration_not_comment_block(self) -> None:
        swift = "import SwiftUI\n" + "// note\n" * 30 + "\nclass VM: ObservableObject {}\n"
        with make_tree({"App/VM.swift": swift}) as tmp:
            _, report = cli_json(tmp, "--check", "apple.mainactor_missing_on_observable")
        finding = report["results"][0]["findings"][0]
        self.assertEqual(finding["line"], 33)

    def test_large_comment_blocks_stay_linear(self) -> None:
        ensure_checks_loaded()
        block = "// " + "x" * 60 + "\n"
        hash_block = "# " + "x" * 60 + "\n"
        n = 6000  # ~400 KB per file; the quadratic version needed seconds per rule
        files = {
            "App/Big.swift": "import SwiftUI\n" + block * n + "struct A {}\n",
            "game/big.gd": "extends Node\n" + hash_block * n + "var a := 1\n",
            "svc/big.py": "import os\n" + hash_block * n + "x = 1\n",
            "api/types.ts": "export type A = string;\n" + block * n,
        }
        with make_tree(files) as tmp:
            ctx = Context(tmp, Config())
            ctx.all_files()
            for check_id in AFFECTED:
                with self.subTest(check=check_id):
                    start = time.perf_counter()
                    REGISTRY[check_id].fn(ctx)
                    self.assertLess(time.perf_counter() - start, 2.0)


if __name__ == "__main__":
    unittest.main()
