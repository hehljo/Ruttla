"""Seeded property / fuzz tests (P03-T008): paths, config, escaping, selectors.

Deterministic seeds keep CI reproducible; raise RUTTLA_FUZZ_ROUNDS locally
for a longer run.
"""

from __future__ import annotations

import os
import random
import string
import unittest

from _support import cli_json, make_tree

from ruttla.config import Config
from ruttla.context import Context
from ruttla.discovery import strip_comments
from ruttla.engine import selector_matches
from ruttla.models import ConfigError, Finding, Severity
from ruttla.reporting.agent import agent_field

ROUNDS = int(os.environ.get("RUTTLA_FUZZ_ROUNDS", "400"))
NASTY = "\t\n\r\x0b\x0c   \"'`/\\*#<>{}[]=:;äöü€😀\x00"


def rand_text(rng: random.Random, n: int) -> str:
    alphabet = string.printable + NASTY
    return "".join(rng.choice(alphabet) for _ in range(n))


class EscapingProperties(unittest.TestCase):
    def test_agent_field_is_always_one_tab_free_line(self) -> None:
        rng = random.Random(1)
        for _ in range(ROUNDS):
            value = agent_field(rand_text(rng, rng.randint(0, 80)))
            self.assertNotIn("\t", value)
            self.assertLessEqual(len(value.splitlines()), 1)
            self.assertNotIn("\n", value)


class CommentStrippingProperties(unittest.TestCase):
    def test_length_and_newlines_are_preserved(self) -> None:
        rng = random.Random(2)
        exts = [".swift", ".ts", ".py", ".ps1", ".html", ".css", ".gd", ".vue", ".txt"]
        for _ in range(ROUNDS):
            text = rand_text(rng, rng.randint(0, 200))
            ext = rng.choice(exts)
            out = strip_comments(text, ext)
            self.assertEqual(len(out), len(text))
            self.assertEqual([i for i, c in enumerate(out) if c == "\n"],
                             [i for i, c in enumerate(text) if c == "\n"])


class SelectorProperties(unittest.TestCase):
    def test_prefix_selector_semantics(self) -> None:
        rng = random.Random(3)
        for _ in range(ROUNDS):
            cid = ".".join(rng.choice(["apple", "web", "x", "release", "a_b"])
                           for _ in range(rng.randint(1, 3)))
            cut = rng.randint(0, len(cid))
            self.assertTrue(selector_matches(cid, cid))
            self.assertTrue(selector_matches(cid[:cut] + "*", cid))
            self.assertFalse(selector_matches(cid + "x", cid))


class ConfigFuzz(unittest.TestCase):
    def test_arbitrary_profiles_never_crash_the_loader(self) -> None:
        rng = random.Random(4)
        fragments = [
            "[gate]\n", "[project]\n", "[brand]\n", "[severity]\n", "[nope]\n",
            "strict = true\n", 'strict = "yes"\n', "max_file_bytes = -1\n",
            "max_file_bytes = 10\n", 'exclude = ["a/**"]\n', "exclude = 3\n",
            'platform = "apple"\n', 'platform = "dotnet"\n', 'name = ""\n',
            '"x.*" = "off"\n', '"x.*" = "fatal"\n', "config_version = 1\n",
            "config_version = 9\n", "= broken\n", '[gate\n', 'names = ["A", 1]\n',
        ]
        for _ in range(ROUNDS):
            text = "".join(rng.choice(fragments) for _ in range(rng.randint(0, 6)))
            with make_tree({".ruttla.toml": text}) as tmp:
                try:
                    cfg = Config.load(tmp)
                except ConfigError:
                    continue
                self.assertIsInstance(cfg, Config)
                self.assertGreater(cfg.max_file_bytes, 0)


class PathRobustness(unittest.TestCase):
    def test_unicode_spaces_and_nested_paths_are_reported_posix(self) -> None:
        files = {
            "dir with space/ümlaut 😀.ts": 'const t = "ghp_' + "b" * 36 + '";\n',
            "a/b/c/d/e/f.ts": "export const ok = 1;\n",
        }
        with make_tree(files) as tmp:
            code, report = cli_json(tmp, "--check", "secrets.hardcoded_credential")
            rels = sorted(f.rel for f in Context(tmp, Config()).all_files())
        self.assertEqual(code, 1)
        finding = report["results"][0]["findings"][0]
        self.assertEqual(finding["file"], "dir with space/ümlaut 😀.ts")
        self.assertEqual(rels, sorted(files))

    def test_inventory_order_is_deterministic(self) -> None:
        files = {f"d{i % 3}/f{i}.py": "x = 1\n" for i in range(30)}
        with make_tree(files) as tmp:
            first = [f.rel for f in Context(tmp, Config()).all_files()]
            second = [f.rel for f in Context(tmp, Config()).all_files()]
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first, key=lambda r: (r.split("/")[0], r)))

    def test_finding_normalizes_windows_backslashes(self) -> None:
        f = Finding(check_id="x.y", severity=Severity.WARNING, message="msg", file="src\\sub\\file.py")
        self.assertEqual(f.file, "src/sub/file.py")


if __name__ == "__main__":
    unittest.main()
