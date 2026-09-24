from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from ruttla.cli import EXIT_CRASH, EXIT_OK, main
from ruttla.update import UPDATE_REQUIREMENT, run_update


class UpdateCommandTests(unittest.TestCase):
    def test_update_installs_main_in_the_active_interpreter(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with (
            mock.patch("ruttla.update.sys.executable", "/python/active"),
            mock.patch("ruttla.update.subprocess.run", return_value=completed) as run,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            result = main(["update"])

        self.assertEqual(result, EXIT_OK)
        run.assert_called_once_with(
            [
                "/python/active", "-m", "pip", "install", "--upgrade",
                "--force-reinstall", UPDATE_REQUIREMENT,
            ],
            check=False,
        )
        self.assertIn("aktualisiert", stdout.getvalue())

    def test_pip_failure_is_exit_three(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=1)
        with (
            mock.patch("ruttla.update.subprocess.run", return_value=completed),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            result = run_update([])

        self.assertEqual(result, EXIT_CRASH)
        self.assertIn("fehlgeschlagen", stderr.getvalue())

    def test_pip_start_failure_is_exit_three(self) -> None:
        with (
            mock.patch("ruttla.update.subprocess.run", side_effect=OSError("missing Python")),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            result = run_update([])

        self.assertEqual(result, EXIT_CRASH)
        self.assertIn("konnte pip nicht starten", stderr.getvalue())

    def test_update_does_not_accept_undocumented_options(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                run_update(["--unknown"])
        self.assertEqual(raised.exception.code, EXIT_CRASH)

    def test_update_help_does_not_run_pip(self) -> None:
        with (
            mock.patch("ruttla.update.subprocess.run") as run,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            with self.assertRaises(SystemExit) as raised:
                main(["update", "--help"])

        self.assertEqual(raised.exception.code, 0)
        run.assert_not_called()
        self.assertIn("ruttla update", stdout.getvalue())



if __name__ == "__main__":
    unittest.main()
