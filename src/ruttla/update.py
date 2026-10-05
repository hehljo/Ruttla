"""Explicit updater for the ``ruttla update`` command.

Scanning remains offline. This opt-in command is the only network path: it
reads the GitHub release, installs the Python package from the release's
commit and puts the matching ``ruttla-engine`` next to the ``ruttla`` script,
where ``declarative.find_engine`` looks for it. Package and engine always come
from the same commit — the package ships the rules, the engine must read
exactly that rule format. A source checkout is never changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request

from .engine import EXIT_CRASH, EXIT_OK

REPO = "hehljo/Ruttla"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
MANIFEST = "ruttla-release.json"
CHECKSUMS = "SHA256SUMS"
TIMEOUT_S = 60


class UpdateError(Exception):
    """Update aborted; the message tells the user what to do."""


class UpdateArgumentParser(argparse.ArgumentParser):
    """Update-command usage errors follow the CLI's exit-3 contract."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_CRASH, f"RUNNER_ERROR\tinvalid_arguments\t{message}\n")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ruttla-update",
                                               "Accept": "application/octet-stream, application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https URLs
        return resp.read()


def engine_target(system: str | None = None, machine: str | None = None) -> str | None:
    """Rust target triple of the release binary for this machine, or None."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine)
    if arch is None:
        return None
    if system == "linux":
        return f"{arch}-unknown-linux-musl"
    if system == "darwin":
        return f"{arch}-apple-darwin"
    if system == "windows" and arch == "x86_64":
        return "x86_64-pc-windows-msvc"
    return None


def select_release(releases: list[dict], channel: str) -> dict | None:
    """``stable``: newest non-prerelease; ``nightly``: the ``nightly`` tag;
    ``auto``: stable if one exists, else nightly."""
    usable = [r for r in releases if not r.get("draft")]
    stable = next((r for r in usable if not r.get("prerelease")), None)
    nightly = next((r for r in usable if r.get("tag_name") == "nightly"), None)
    if channel == "stable":
        return stable
    if channel == "nightly":
        return nightly
    return stable or nightly


def parse_checksums(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def _verified(name: str, data: bytes, sums: dict[str, str]) -> bytes:
    want = sums.get(name)
    if want is None:
        raise UpdateError(f"{name} fehlt in {CHECKSUMS} — Release unvollständig, Update abgebrochen.")
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise UpdateError(f"Prüfsumme von {name} stimmt nicht ({got} statt {want}) — Update abgebrochen.")
    return data


def package_requirement(ref: str) -> str:
    """Archiv statt git+URL: pip braucht dafür kein installiertes git."""
    return f"ruttla @ https://github.com/{REPO}/archive/{ref}.tar.gz"


def _pip_install(requirement: str) -> None:
    command = [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall", requirement]
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        raise UpdateError(f"Ruttla-Update konnte pip nicht starten: {exc}") from exc
    if result.returncode != 0:
        raise UpdateError(f"Ruttla-Update fehlgeschlagen (pip Exit {result.returncode}). "
                          "Prüf die pip-Meldung oben und deine Python-Umgebung.")


def install_engine(data: bytes, filename: str, scripts_dir: str) -> str:
    """Write the binary atomically next to the ``ruttla`` script."""
    os.makedirs(scripts_dir, exist_ok=True)
    target = os.path.join(scripts_dir, filename)
    fd, tmp = tempfile.mkstemp(dir=scripts_dir, prefix=".ruttla-engine-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, os.stat(tmp).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return target


def _update(channel: str) -> None:
    try:
        releases = json.loads(_get(RELEASES_API))
    except (OSError, ValueError) as exc:
        raise UpdateError(f"GitHub-Releases nicht lesbar: {exc}") from exc
    release = select_release(releases, channel)
    if release is None:
        raise UpdateError(f"Kein Release im Kanal {channel!r} gefunden.")
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    if CHECKSUMS not in assets or MANIFEST not in assets:
        raise UpdateError(f"Release {release.get('tag_name')} ohne {CHECKSUMS}/{MANIFEST} — Update abgebrochen.")
    sums = parse_checksums(_get(assets[CHECKSUMS]).decode("utf-8"))
    manifest = json.loads(_verified(MANIFEST, _get(assets[MANIFEST]), sums))
    commit = str(manifest.get("commit", ""))
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise UpdateError(f"{MANIFEST}: kein gültiger Commit ({commit!r}) — Update abgebrochen.")

    print(f"Aktualisiere Ruttla auf {release.get('tag_name')} ({manifest.get('version')}, {commit[:7]}) …")
    _pip_install(package_requirement(commit))

    target = engine_target()
    exe = ".exe" if os.name == "nt" else ""
    asset = f"ruttla-engine-{target}{exe}" if target else None
    if asset is None or asset not in assets:
        print(f"Für {platform.system()}/{platform.machine()} gibt es keine fertige Engine. Die "
              "deklarativen Regeln bleiben 'nicht gemessen', bis du sie selbst baust "
              "(cargo build --release --manifest-path engine/Cargo.toml, dann RUTTLA_ENGINE_BIN).",
              file=sys.stderr)
        return
    data = _verified(asset, _get(assets[asset]), sums)
    path = install_engine(data, f"ruttla-engine{exe}", sysconfig.get_path("scripts"))
    check = subprocess.run([path, "--version"], check=False, capture_output=True, text=True)
    if check.returncode != 0:
        raise UpdateError(f"Installierte Engine startet nicht ({path}): {check.stderr.strip()}")
    print(f"Engine installiert: {path} ({check.stdout.strip()})")


def run_update(argv: list[str], prog: str = "ruttla") -> int:
    """Install package and engine of the selected GitHub release."""
    parser = UpdateArgumentParser(
        prog=f"{prog} update",
        description="Installiert Ruttla und die passende Engine aus dem GitHub-Release "
                    "in der aktiven Python-Umgebung.",
    )
    parser.add_argument("--channel", choices=["auto", "stable", "nightly"], default="auto",
                        help="auto (Vorgabe): letztes Release, sonst nightly aus main")
    args = parser.parse_args(argv)
    try:
        _update(args.channel)
    except UpdateError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CRASH
    print("Ruttla ist aktualisiert. Starte den Befehl für den neuen Stand erneut.")
    return EXIT_OK
