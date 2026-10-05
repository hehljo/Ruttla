"""Differential test: Rust inventory == Python inventory (P11-T002).

Every scenario is built once and measured by both implementations; the
comparison logic is imported from scripts/engine_diff.py, not rebuilt.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from _support import REPO, require_engine

from ruttla.config import Config

_spec = importlib.util.spec_from_file_location("engine_diff", REPO / "scripts" / "engine_diff.py")
engine_diff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_diff)


def _write(root: Path, rel: str, text: str = "x\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _symlink(target: str, link: Path, case: unittest.TestCase) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        case.skipTest(f"symlinks unavailable: {exc}")


class EngineInventoryParity(unittest.TestCase):
    def setUp(self) -> None:
        self.binary = require_engine(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def assertSame(self, config: Config | None = None) -> dict:
        config = config or Config()
        a = engine_diff.python_inventory(str(self.root), config)
        b = engine_diff.engine_inventory(self.binary, str(self.root), config)
        self.assertEqual(engine_diff.diff(a, b), [])
        self.assertEqual(a, b)
        return a

    def test_order_unicode_case_and_extensions(self) -> None:
        for rel in ("b.py", "B.py", "a/z.TS", "a/ä ö.swift", "Ä/x.gd", "a b/c.d.e",
                    ".hidden", "..x", ".a.b", "file.", "Makefile", "z/y/x/w.rs", "_/1.txt"):
            _write(self.root, rel)
        out = self.assertSame()
        self.assertEqual(out["coverage"]["files_scanned"], 13)

    def test_excluded_directories_and_agent_files(self) -> None:
        for rel in ("node_modules/x.js", "build/y.py", "sub/build/z.py", "Assets.xcassets/c.json",
                    "keep/a.py", "own/skip.py", "CLAUDE.md", "deep/AGENTS.md", "README.md",
                    "x/.ruttla.toml"):
            _write(self.root, rel)
        config = Config()
        config.exclude_dirs = ["own"]
        out = self.assertSame(config)
        self.assertEqual(out["coverage"]["files_excluded_agent_instructions"], 3)

    def test_exclude_globs_with_python_fnmatch_semantics(self) -> None:
        for rel in ("docs/a.md", "docs/sub/b.txt", "a1.txt", "b2.txt", "c3.txt", "x[", "ab.py",
                    "cd.py", "-z", "az", "k\\l", "q.md"):
            try:
                _write(self.root, rel)
            except OSError:
                continue
        config = Config()
        config.exclude_globs = ["docs/*", "[ab]*.txt", "x[", "[!c]?.py", "[c-a]", "[a-]z", "*.MD"]
        self.assertSame(config)

    def test_max_file_bytes_skips_are_reported(self) -> None:
        _write(self.root, "small.py", "x")
        _write(self.root, "big.py", "x" * 50)
        config = Config()
        config.max_file_bytes = 10
        out = self.assertSame(config)
        self.assertEqual(out["coverage"]["files_skipped_total"], 1)

    def test_symlink_alias_broken_and_loop(self) -> None:
        _write(self.root, "src/real.py")
        _symlink("real.py", self.root / "src/alias.py", self)
        _write(self.root, "node_modules/hidden.py")
        _symlink("../node_modules/hidden.py", self.root / "lib/via.py", self)
        _symlink("missing.py", self.root / "src/gone.py", self)
        _symlink("loop_b", self.root / "loop_a", self)
        _symlink("loop_a", self.root / "loop_b", self)
        _write(self.root, "dir/inner.py")
        _symlink("dir", self.root / "dirlink", self)
        out = self.assertSame()
        self.assertEqual(out["coverage"]["files_skipped_symlink_alias"], 1)
        self.assertIn("src/gone.py", out["coverage"]["files_skipped_broken_symlink"])

    def test_link_leaving_the_root_is_an_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            _write(Path(outside), "secret.txt")
            _symlink(os.path.join(outside, "secret.txt"), self.root / "leak.txt", self)
            out = self.assertSame()
        self.assertEqual(out["error"]["kind"], "outside_root")

    def test_broken_link_pointing_outside_is_still_an_error(self) -> None:
        _symlink("/nonexistent-ruttla/target.py", self.root / "out.py", self)
        out = self.assertSame()
        self.assertEqual(out["error"]["kind"], "outside_root")

    def test_empty_root(self) -> None:
        out = self.assertSame()
        self.assertEqual(out["files"], [])


if __name__ == "__main__":
    unittest.main()


class DiffReportsDivergence(unittest.TestCase):
    """The comparison itself must be able to go red (no engine needed)."""

    BASE = {"files": [{"rel": "a.py", "ext": ".py"}],
            "coverage": {"files_scanned": 1, "files_skipped_symlink_alias": 0}}

    def test_identical_is_empty(self) -> None:
        self.assertEqual(engine_diff.diff(self.BASE, dict(self.BASE)), [])

    def test_missing_file_order_and_coverage_are_reported(self) -> None:
        other = {"files": [], "coverage": dict(self.BASE["coverage"], files_scanned=0)}
        problems = engine_diff.diff(self.BASE, other)
        self.assertIn("nur Python: a.py", problems)
        self.assertTrue(any("files_scanned" in p for p in problems))
        swapped = {"files": [{"rel": "b.py", "ext": ".py"}, {"rel": "a.py", "ext": ".py"}],
                   "coverage": self.BASE["coverage"]}
        reordered = {"files": list(reversed(swapped["files"])), "coverage": self.BASE["coverage"]}
        self.assertEqual(engine_diff.diff(swapped, reordered), ["gleiche Dateien, andere Reihenfolge"])
        ext = {"files": [{"rel": "a.py", "ext": ".PY"}], "coverage": self.BASE["coverage"]}
        self.assertEqual(engine_diff.diff(self.BASE, ext), ["Endungen weichen ab"])

    def test_error_versus_result_is_reported(self) -> None:
        err = {"error": {"kind": "outside_root", "message": "x"}}
        self.assertEqual(len(engine_diff.diff(self.BASE, err)), 1)
