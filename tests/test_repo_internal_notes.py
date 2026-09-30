"""repo.internal_notes_published im echten Git-Repository.

Die Self-Tests laufen ohne Git; hier wird der Git-Zweig gemessen: getrackt
und neu-nicht-ignoriert ist veröffentlicht, ignoriert ist lokal — und das
alles nur in einem öffentlichen Repo. Die Sichtbarkeitsabfrage wird ersetzt,
damit der Test offline läuft.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from unittest import mock

from _support import ensure_checks_loaded

# Erst die ganze Registry laden: ein Direktimport registriert sonst nur
# diesen einen Check, und ensure_checks_loaded() hielte sie für vollständig.
ensure_checks_loaded()

from ruttla.checks.universal import repo  # noqa: E402
from ruttla.config import Config  # noqa: E402
from ruttla.context import Context  # noqa: E402
from ruttla.models import Status  # noqa: E402


def _git(root: str, *args: str) -> None:
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)


def _write(root: str, rel: str, text: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class InternalNotesInGit(unittest.TestCase):
    visibility: str | None = "public"

    def run_check(self, root: str, allow_network: bool = True):
        config = Config()
        config.allow_network = allow_network
        with mock.patch.object(repo, "github_visibility",
                               return_value=self.visibility) as probe:
            result = repo.check_internal_notes_published(Context(root, config))
        self.probe = probe
        return result

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _git(self.root, "init", "-q")
        _git(self.root, "remote", "add", "origin", "git@github.com:someone/app.git")
        _write(self.root, "README.md", "# App\n")
        _write(self.root, "HANDOVER.md", "# Übergabe\n")
        _write(self.root, "MASTER_ROADMAP.md", "# Roadmap\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_tracked_notes_fail(self) -> None:
        _git(self.root, "add", ".")
        result = self.run_check(self.root)
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(sorted(f.file for f in result.findings),
                         ["HANDOVER.md", "MASTER_ROADMAP.md"])

    def test_new_unignored_notes_fail(self) -> None:
        result = self.run_check(self.root)
        self.assertEqual(result.status, Status.FAIL)

    def test_ignored_notes_pass(self) -> None:
        _write(self.root, ".gitignore", "HANDOVER.md\nMASTER_ROADMAP.md\n")
        _git(self.root, "add", ".")
        result = self.run_check(self.root)
        self.assertEqual(result.status, Status.PASS)
        self.assertGreater(result.units_examined, 0)

    def test_ignored_but_still_tracked_fails(self) -> None:
        _git(self.root, "add", ".")
        _write(self.root, ".gitignore", "HANDOVER.md\nMASTER_ROADMAP.md\n")
        result = self.run_check(self.root)
        self.assertEqual(result.status, Status.FAIL)

    def test_private_repo_passes(self) -> None:
        self.visibility = "private"
        _git(self.root, "add", ".")
        result = self.run_check(self.root)
        self.assertEqual(result.status, Status.PASS)
        self.probe.assert_called_once_with("someone", "app")

    def test_visibility_unknown_is_unmeasured(self) -> None:
        self.visibility = None
        _git(self.root, "add", ".")
        self.assertEqual(self.run_check(self.root).status, Status.UNMEASURED)

    def test_without_network_is_unmeasured_and_offline(self) -> None:
        _git(self.root, "add", ".")
        result = self.run_check(self.root, allow_network=False)
        self.assertEqual(result.status, Status.UNMEASURED)
        self.probe.assert_not_called()

    def test_no_github_remote_is_unmeasured(self) -> None:
        _git(self.root, "remote", "remove", "origin")
        _git(self.root, "add", ".")
        self.assertEqual(self.run_check(self.root).status, Status.UNMEASURED)


if __name__ == "__main__":
    unittest.main()
