"""Explicit updater for the ``ruttla update`` command.

Scanning remains offline. This opt-in command is the only network path: it
reads the GitHub release (direct download URLs, no API), installs the Python
package from the release's commit and puts the matching ``ruttla-engine`` next to the ``ruttla`` script,
where ``declarative.find_engine`` looks for it. Package and engine always come
from the same commit — the package ships the rules, the engine must read
exactly that rule format. A source checkout is never changed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import stat
import subprocess
import sys
import sysconfig
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .engine import EXIT_CRASH, EXIT_OK

REPO = "hehljo/Ruttla"
# Direkte Download-Adressen statt der Releases-API: die API erlaubt ohne
# Anmeldung 60 Abfragen je Stunde und IP — auf einem geteilten CI-Runner
# (belegt 2026-10-05, macOS-Smoke `HTTP 403 rate limit exceeded`) oder hinter
# einem geteilten Netzanschluss ist das schnell aufgebraucht. `latest` ist das
# neueste veröffentlichte Release ohne Vorab- und Entwurfsstatus.
CHANNEL_BASES = {
    "stable": f"https://github.com/{REPO}/releases/latest/download/",
    "nightly": f"https://github.com/{REPO}/releases/download/nightly/",
}
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


def _fetch(url: str) -> bytes | None:
    """Inhalt, oder None, wenn es die Datei im Release nicht gibt (404)."""
    try:
        return _get(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise UpdateError(f"GitHub-Release nicht lesbar: {exc}") from exc
    except OSError as exc:
        raise UpdateError(f"GitHub-Release nicht lesbar: {exc}") from exc


def channels(channel: str) -> list[str]:
    """``auto``: stable, falls es eins gibt, sonst nightly."""
    return ["stable", "nightly"] if channel == "auto" else [channel]


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


def externally_managed() -> bool:
    """PEP 668: System-Python außerhalb einer venv, dessen pip Installationen ablehnt."""
    if sys.prefix != sys.base_prefix:
        return False
    return (Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED").is_file()


def editable_install() -> bool:
    """Läuft Ruttla aus einem Checkout (``pip install -e``)? Dann gehört dort ``git pull`` hin."""
    try:
        raw = importlib.metadata.distribution("ruttla").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return False
    try:
        info = json.loads(raw or "{}")
    except ValueError:
        return False
    return isinstance(info, dict) and bool((info.get("dir_info") or {}).get("editable"))


def environment_problem() -> str | None:
    """Was ``pip install`` in dieser Umgebung verhindert oder zerstören würde — vor jedem Download."""
    if editable_install():
        return ("Ruttla läuft aus einem Checkout (pip install -e). Ein Update würde ihn durch eine "
                "Archivkopie ersetzen — stattdessen im Checkout `git pull` und die Engine mit "
                "`cargo build --release --manifest-path engine/Cargo.toml` neu bauen.")
    if externally_managed():
        return (f"{sys.executable} ist systemverwaltet (PEP 668) — pip lehnt die Installation dort ab. "
                "Ruttla in einer venv oder mit pipx installieren und das Update dort ausführen.")
    return None


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
        hint = ("Unter Windows sperrt die laufende ruttla.exe ihre eigene Datei (WinError 32) — "
                f"dann `{sys.executable} -m ruttla update`." if os.name == "nt" else "")
        raise UpdateError(f"Ruttla-Update fehlgeschlagen (pip Exit {result.returncode}). "
                          f"Prüf die pip-Meldung oben und deine Python-Umgebung. {hint}".rstrip())


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
    problem = environment_problem()
    if problem is not None:
        raise UpdateError(problem)
    for name in channels(channel):
        base = CHANNEL_BASES[name]
        raw_sums = _fetch(base + CHECKSUMS)
        if raw_sums is not None:
            break
    else:
        raise UpdateError(f"Kein Release im Kanal {channel!r} gefunden.")
    try:
        sums = parse_checksums(raw_sums.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise UpdateError(f"{CHECKSUMS} ist kein Text — Update abgebrochen.") from exc
    raw_manifest = _fetch(base + MANIFEST)
    if raw_manifest is None:
        raise UpdateError(f"Release {name} ohne {MANIFEST} — Update abgebrochen.")
    try:
        manifest = json.loads(_verified(MANIFEST, raw_manifest, sums))
    except ValueError as exc:
        raise UpdateError(f"{MANIFEST} ist kein gültiges JSON — Update abgebrochen.") from exc
    if not isinstance(manifest, dict):
        raise UpdateError(f"{MANIFEST} ist kein JSON-Objekt — Update abgebrochen.")
    commit = str(manifest.get("commit", ""))
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise UpdateError(f"{MANIFEST}: kein gültiger Commit ({commit!r}) — Update abgebrochen.")

    target = engine_target()
    exe = ".exe" if os.name == "nt" else ""
    asset = f"ruttla-engine-{target}{exe}" if target else None
    # Was das Release enthält, sagt SHA256SUMS — ohne Eintrag keine Anfrage.
    data = _fetch(base + asset) if asset is not None and asset in sums else None
    # Engine vor pip prüfen: eine abgelehnte Engine darf kein halbes Update hinterlassen.
    if data is not None:
        data = _verified(asset, data, sums)

    print(f"Aktualisiere Ruttla auf {name} ({manifest.get('version')}, {commit[:7]}) …")
    _pip_install(package_requirement(commit))

    if data is None:
        print(f"Für {platform.system()}/{platform.machine()} gibt es keine fertige Engine. Die "
              "deklarativen Regeln bleiben 'nicht gemessen', bis du sie selbst baust "
              "(cargo build --release --manifest-path engine/Cargo.toml, dann RUTTLA_ENGINE_BIN).",
              file=sys.stderr)
        return
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
