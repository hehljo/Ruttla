from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from ruttla.cli import EXIT_CRASH, EXIT_OK, main
from ruttla.update import CHANNEL_BASES, REPO as GH_REPO, channels, engine_target, run_update

COMMIT = "a" * 40
TARGET = "x86_64-unknown-linux-musl"
ENGINE = b"\x7fELF-engine"


def _release(*, manifest: dict | None = None, engine: bytes = ENGINE, sums_engine: bytes = ENGINE,
             with_engine: bool = True, channel: str = "stable") -> dict[str, bytes]:
    """URL → Inhalt eines Releases; SHA256SUMS wird aus `sums_engine` gebildet."""
    manifest_raw = json.dumps(manifest or {"commit": COMMIT, "version": "0.1.0", "channel": channel}).encode()
    base = CHANNEL_BASES[channel]
    files = {"ruttla-release.json": manifest_raw}
    if with_engine:
        files[f"ruttla-engine-{TARGET}"] = engine
    sums = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    if with_engine:
        sums[f"ruttla-engine-{TARGET}"] = hashlib.sha256(sums_engine).hexdigest()
    files["SHA256SUMS"] = "".join(f"{h}  {n}\n" for n, h in sums.items()).encode()
    return {base + n: data for n, data in files.items()}


def _served(urls: dict[str, bytes], requested: list[str] | None = None):
    """`_get`-Ersatz: unbekannte Adresse = 404 wie bei GitHub."""
    def get(url: str) -> bytes:
        if requested is not None:
            requested.append(url)
        if url not in urls:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return urls[url]
    return get


class UpdateCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.scripts = self._tmp.name
        self.calls: list[list[str]] = []
        self.requested: list[str] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, urls: dict[str, bytes], *, pip_rc: int = 0, argv: list[str] | None = None):
        def fake_run(cmd, **_kw):
            self.calls.append(list(cmd))
            if cmd[1:3] == ["-m", "pip"]:
                return subprocess.CompletedProcess(cmd, pip_rc)
            return subprocess.CompletedProcess(cmd, 0, stdout="ruttla-engine 0.1.0", stderr="")
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch("ruttla.update._get", side_effect=_served(urls, self.requested)),
            mock.patch("ruttla.update.subprocess.run", side_effect=fake_run),
            mock.patch("ruttla.update.sys.executable", "/python/active"),
            mock.patch("ruttla.update.engine_target", return_value=TARGET),
            # platform.system() ruft unter Windows/Python 3.11 selbst `cmd /c ver`
            # über subprocess auf — ohne Patch landet das im gezählten Mock.
            mock.patch("ruttla.update.platform.system", return_value="Linux"),
            mock.patch("ruttla.update.platform.machine", return_value="x86_64"),
            mock.patch("ruttla.update.os.name", "posix"),
            mock.patch("ruttla.update.sysconfig.get_path", return_value=self.scripts),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = main(["update", *(argv or [])])
        return code, out.getvalue(), err.getvalue()

    def _engine_path(self) -> Path:
        return Path(self.scripts, "ruttla-engine")

    def test_installs_package_and_engine_from_the_same_commit(self) -> None:
        code, out, _ = self._run(_release())
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(self.calls[0], ["/python/active", "-m", "pip", "install", "--upgrade",
                                         "--force-reinstall", f"ruttla @ https://github.com/{GH_REPO}/archive/{COMMIT}.tar.gz"])
        self.assertEqual(self._engine_path().read_bytes(), ENGINE)
        self.assertTrue(os.access(self._engine_path(), os.X_OK))
        self.assertEqual(self.calls[1], [str(self._engine_path()), "--version"])
        self.assertIn("aktualisiert", out)

    def test_tampered_engine_is_not_installed(self) -> None:
        code, _, err = self._run(_release(engine=b"evil", sums_engine=ENGINE))
        self.assertEqual(code, EXIT_CRASH)
        self.assertIn("Prüfsumme", err)
        self.assertFalse(self._engine_path().exists())

    def test_invalid_commit_stops_before_pip(self) -> None:
        code, _, err = self._run(_release(manifest={"commit": "main; rm -rf /"}))
        self.assertEqual(code, EXIT_CRASH)
        self.assertIn("kein gültiger Commit", err)
        self.assertEqual(self.calls, [])

    def test_missing_engine_for_platform_keeps_package_and_says_so(self) -> None:
        code, _, err = self._run(_release(with_engine=False))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("nicht gemessen", err)

    def test_pip_failure_is_exit_three(self) -> None:
        code, _, err = self._run(_release(), pip_rc=1)
        self.assertEqual(code, EXIT_CRASH)
        self.assertIn("fehlgeschlagen", err)
        self.assertFalse(self._engine_path().exists())

    def test_pip_start_failure_is_exit_three(self) -> None:
        urls = _release()
        with (
            mock.patch("ruttla.update._get", side_effect=_served(urls)),
            mock.patch("ruttla.update.subprocess.run", side_effect=OSError("missing Python")),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            result = run_update([])
        self.assertEqual(result, EXIT_CRASH)
        self.assertIn("konnte pip nicht starten", stderr.getvalue())

    def test_no_api_request_only_release_downloads(self) -> None:
        # Die Releases-API ist ohne Anmeldung auf 60 Abfragen/h je IP begrenzt.
        code, _, _ = self._run(_release())
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(self.requested)
        for url in self.requested:
            self.assertTrue(url.startswith(f"https://github.com/{GH_REPO}/releases/"), url)

    def test_auto_falls_back_to_nightly_without_stable(self) -> None:
        code, out, _ = self._run(_release(channel="nightly"))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("nightly", out)
        self.assertEqual(self.requested[0], CHANNEL_BASES["stable"] + "SHA256SUMS")

    def test_stable_channel_without_stable_release_stops(self) -> None:
        code, _, err = self._run(_release(channel="nightly"), argv=["--channel", "stable"])
        self.assertEqual(code, EXIT_CRASH)
        self.assertIn("Kein Release", err)
        self.assertEqual(self.calls, [])

    def test_unreadable_release_list_is_exit_three(self) -> None:
        with (
            mock.patch("ruttla.update._get", side_effect=OSError("offline")),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(run_update([]), EXIT_CRASH)
        self.assertIn("nicht lesbar", stderr.getvalue())

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


class ChannelTests(unittest.TestCase):
    def test_auto_tries_stable_then_nightly(self) -> None:
        self.assertEqual(channels("auto"), ["stable", "nightly"])
        self.assertEqual(channels("nightly"), ["nightly"])
        self.assertTrue(CHANNEL_BASES["stable"].endswith("/releases/latest/download/"))


class EngineTargetTests(unittest.TestCase):
    def test_release_matrix_platforms(self) -> None:
        cases = {
            ("Linux", "x86_64"): "x86_64-unknown-linux-musl",
            ("Linux", "aarch64"): "aarch64-unknown-linux-musl",
            ("Darwin", "arm64"): "aarch64-apple-darwin",
            ("Darwin", "x86_64"): "x86_64-apple-darwin",
            ("Windows", "AMD64"): "x86_64-pc-windows-msvc",
            ("Windows", "ARM64"): None,
            ("FreeBSD", "amd64"): None,
            ("Linux", "riscv64"): None,
        }
        for (system, machine), want in cases.items():
            self.assertEqual(engine_target(system, machine), want, (system, machine))

    def test_every_target_is_built_by_the_release_workflow(self) -> None:
        workflow = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        for system, machine in [("Linux", "x86_64"), ("Linux", "aarch64"), ("Darwin", "arm64"),
                                ("Darwin", "x86_64"), ("Windows", "AMD64")]:
            self.assertIn(f"target: {engine_target(system, machine)}", workflow)


if __name__ == "__main__":
    unittest.main()
