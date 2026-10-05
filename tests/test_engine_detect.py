"""Differential test: Rust detection == Python detection (P11-T003).

Same manifest file, same validation, same roots and claims. Comparison
logic comes from scripts/engine_diff.py.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from _support import REPO, require_engine

from ruttla.config import Config
from ruttla.platforms import ManifestError, parse_manifest

_spec = importlib.util.spec_from_file_location("engine_diff", REPO / "scripts" / "engine_diff.py")
engine_diff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_diff)

MANIFEST = (REPO / "src" / "ruttla" / "platforms.toml").read_text(encoding="utf-8")
PACK_FIXTURES = REPO / "tests" / "fixtures" / "packs"


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


class EngineDetectParity(unittest.TestCase):
    def setUp(self) -> None:
        self.binary = require_engine(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def assertSame(self, root: Path | None = None, config: Config | None = None) -> dict:
        root = root or self.root
        config = config or Config()
        a = engine_diff.python_detect(str(root), config)
        b = engine_diff.engine_detect(self.binary, str(root), config)
        self.assertEqual(engine_diff.diff(a, b), [], str(root))
        self.assertEqual(a, b)
        return a

    def test_every_pack_fixture(self) -> None:
        dirs = sorted(p for p in PACK_FIXTURES.glob("*/*") if p.is_dir())
        self.assertGreater(len(dirs), 10)
        for d in dirs:
            with self.subTest(fixture=str(d.relative_to(REPO))):
                self.assertSame(d)

    def test_mixed_repo_with_nested_claims(self) -> None:
        _write(self.root, "game/ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.0\n")
        _write(self.root, "game/Assets/Player.cs", "class Player {}\n")
        _write(self.root, "game/sub/tool/Tool.csproj", "<Project/>\n")
        _write(self.root, "game/sub/tool/Tool.cs", "class Tool {}\n")
        _write(self.root, "ue/Shooter.uproject", "{}\n")
        _write(self.root, "ue/Source/Shooter.Build.cs", "class B {}\n")
        _write(self.root, "ue/Source/A.h", "UCLASS()\nclass A {};\n")
        _write(self.root, "desk/App.csproj", "<Project/>\n")
        _write(self.root, "desk/App.xaml.cs", "class App {}\n")
        _write(self.root, "web/package.json", "{}\n")
        _write(self.root, "ios/App.xcodeproj/project.pbxproj", "// !$*UTF8*$!\n")
        out = self.assertSame()
        self.assertIn("unity", out["platforms"])

    def test_content_signal_respects_requires_and_rule_files(self) -> None:
        _write(self.root, "gates.py", "def test_gpio():\n    pass\nimport gpiozero\n")
        self.assertNotIn("raspberry", self.assertSame()["platforms"])
        _write(self.root, "sensor.py", "x = 1\r\nimport serial\r\n")
        self.assertIn("raspberry", self.assertSame()["platforms"])

    def test_unreal_content_without_project_file(self) -> None:
        _write(self.root, "Source/Thing.h", "  GENERATED_BODY()\n")
        _write(self.root, "Source/Other.h", "MY_UCLASS()\n")
        self.assertIn("unreal", self.assertSame()["platforms"])

    def test_dir_suffix_and_exclude_glob_on_directories(self) -> None:
        (self.root / "Old.xcodeproj").mkdir()
        (self.root / "keep").mkdir()
        self.assertIn("apple", self.assertSame()["platforms"])
        config = Config()
        config.exclude_globs = ["Old.xcodeproj/"]
        self.assertNotIn("apple", self.assertSame(config=config)["platforms"])
        config.exclude_globs = ["Old.*"]
        self.assertNotIn("apple", self.assertSame(config=config)["platforms"])

    def test_file_names_are_case_insensitive_suffixes_are_not(self) -> None:
        _write(self.root, "a/PACKAGE.JSON", "{}\n")
        _write(self.root, "b/MyBuild.cs", "class X {}\n")
        _write(self.root, "c/thing.build.cs", "class Y {}\n")
        self.assertSame()


BROKEN_MANIFESTS = {
    "version 2": MANIFEST.replace("manifest_version = 1", "manifest_version = 2"),
    "version true": MANIFEST.replace("manifest_version = 1", "manifest_version = true"),
    "unknown top key": MANIFEST + "\nextra = 1\n",
    "unknown platform key": MANIFEST.replace("[platforms.python]\npack = true",
                                             "[platforms.python]\npack = true\ncolour = 'x'"),
    "pack not bool": MANIFEST.replace("[platforms.python]\npack = true", "[platforms.python]\npack = 1"),
    "example misses": MANIFEST.replace('"import gpiozero", ', '"import nothing", '),
    "counter example hits": MANIFEST.replace('"import boardgame", ', '"import gpiozero", '),
    "lookbehind": MANIFEST.replace(r"\b(?:UCLASS", r"(?<!MY_)\b(?:UCLASS"),
    "claims without root": MANIFEST.replace('[platforms.python]\npack = true',
                                            '[platforms.python]\npack = true\nclaims = [".py"]'),
    "no signal": MANIFEST.replace('[platforms.python]\npack = true\nextensions = [".py"]',
                                  "[platforms.python]\npack = true"),
    "unknown requires": MANIFEST.replace('requires = ["python"]', 'requires = ["cobol"]'),
    "bad marker": MANIFEST.replace('root_markers = ["package.json"]', 'root_markers = ["../package.json"]'),
    "empty string": MANIFEST.replace('extensions = [".gd"]', 'extensions = [""]'),
    "not toml": "manifest_version = = 1",
}


class ManifestValidationParity(unittest.TestCase):
    def setUp(self) -> None:
        self.binary = require_engine(self)

    def _python_accepts(self, text: str) -> bool:
        try:
            parse_manifest(tomllib.loads(text))
        except (ManifestError, tomllib.TOMLDecodeError):
            return False
        return True

    def _engine_accepts(self, text: str) -> bool:
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as fh:
            fh.write(text)
        try:
            proc = subprocess.run([str(self.binary), "check-manifest", fh.name],
                                  capture_output=True, text=True, timeout=60)
        finally:
            os.unlink(fh.name)
        self.assertIn(proc.returncode, (0, 3), proc.stderr)
        return proc.returncode == 0

    def test_shipped_manifest_is_accepted_by_both(self) -> None:
        self.assertTrue(self._python_accepts(MANIFEST))
        self.assertTrue(self._engine_accepts(MANIFEST))

    def test_broken_manifests_are_rejected_by_both(self) -> None:
        for name, text in BROKEN_MANIFESTS.items():
            with self.subTest(name):
                self.assertNotEqual(text, MANIFEST)
                rust = self._engine_accepts(text)
                if name == "lookbehind":
                    # Python's re accepts lookbehind; the engine rejects it at
                    # load (ADR-0011). Intended divergence, measured here.
                    self.assertTrue(self._python_accepts(text))
                    self.assertFalse(rust)
                    continue
                if name == "version true":
                    # Python compares with != (True == 1); same in the engine.
                    self.assertEqual(self._python_accepts(text), rust)
                    continue
                self.assertFalse(self._python_accepts(text))
                self.assertFalse(rust)


if __name__ == "__main__":
    unittest.main()
