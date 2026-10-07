"""apple.required_reason_api_undeclared bleibt in der Prüfwurzel.

Die Pfade lokaler Pakete kommen aus einer fremden Package.swift. Ohne Grenze
liest der Check, was dort steht — ein Nachbarverzeichnis, über einen Link das
halbe Dateisystem. Die Selbsttests des Checks können das nicht zeigen: sie
legen nur Dateien unterhalb der Wurzel an.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from _support import ensure_checks_loaded

ensure_checks_loaded()

from ruttla.checks.apple import required_reason  # noqa: E402
from ruttla.config import Config  # noqa: E402
from ruttla.context import Context  # noqa: E402
from ruttla.models import Status  # noqa: E402


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class RequiredReasonStaysInRoot(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        self.repo = os.path.join(self.base, "repo")
        self.outside = os.path.join(self.base, "outside")
        _write(os.path.join(self.outside, "Sources", "Store.swift"), "UserDefaults.standard\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self):
        return required_reason.check_required_reason(Context(self.repo, Config()))

    def _package(self, path: str) -> None:
        _write(os.path.join(self.repo, "ios", "Package.swift"),
               f'.package(name: "P", path: "{path}")\n')

    def test_package_inside_root_is_measured(self) -> None:
        _write(os.path.join(self.repo, "node_modules", "p", "Store.swift"), "UserDefaults.standard\n")
        self._package("../node_modules/p")
        self.assertEqual(self._run().status, Status.FAIL)

    def test_package_path_outside_root_is_not_read(self) -> None:
        self._package("../../outside")
        result = self._run()
        self.assertEqual(result.status, Status.UNMEASURED)
        self.assertIn("außerhalb", result.reason)

    def test_symlinked_package_outside_root_is_not_read(self) -> None:
        link = os.path.join(self.repo, "node_modules", "p")
        os.makedirs(os.path.dirname(link))
        try:
            os.symlink(self.outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Links nicht anlegbar")
        self._package("../node_modules/p")
        self.assertEqual(self._run().status, Status.UNMEASURED)


if __name__ == "__main__":
    unittest.main()
