"""Healthy local package precedes isolated missing path/manifest controls."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest

from _support import make_tree, ensure_checks_loaded

ensure_checks_loaded()
from ruttla.core import Config, Context, Status
from ruttla.checks.apple.local_packages import check_local_packages


class LocalPackageTests(unittest.TestCase):
    def test_healthy_before_isolated_missing_directory_and_manifest(self):
        with make_tree({
            "App/Package.swift": '.package(name: "Plugin", path: "../node_modules/plugin")',
            "node_modules/plugin/Package.swift": "import PackageDescription\n",
        }) as root:
            run = lambda: check_local_packages(Context(root, Config()))
            self.assertEqual(run().status, Status.PASS)
            manifest = Path(root, "node_modules/plugin/Package.swift")
            data = manifest.read_text()
            manifest.unlink()
            self.assertEqual(run().status, Status.FAIL)
            manifest.parent.rmdir()
            self.assertEqual(run().status, Status.FAIL)
            manifest.parent.mkdir()
            manifest.write_text(data)
            self.assertEqual(run().status, Status.PASS)

    def test_dynamic_comment_and_literal_examples_are_unknown(self):
        for source in [
            '// .package(path: "missing")',
            '/* .package(path: "missing") */',
            '.package(path: prefix + "/missing")',
            '.package(path: "\\(prefix)/missing")',
            'let text = #".package(path: "missing")"#',
            'let text = """\n.package(path: "missing")\n"""',
        ]:
            with self.subTest(source=source), make_tree({"Package.swift": source}) as root:
                self.assertEqual(check_local_packages(Context(root, Config())).status,
                                 Status.UNMEASURED)

    def test_existing_external_symlink_remains_unknown(self):
        with make_tree({"App/Package.swift": '.package(path: "../plugin")'}) as root, \
                tempfile.TemporaryDirectory() as outside:
            # Verzeichnislink mit vorhandenem Ziel: Windows legt ohne
            # target_is_directory einen Dateilink an, und "/tmp" gibt es dort nicht.
            os.symlink(outside, Path(root, "plugin"), target_is_directory=True)
            self.assertEqual(check_local_packages(Context(root, Config())).status,
                             Status.UNMEASURED)
