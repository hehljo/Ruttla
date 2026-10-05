"""Gate-Hub v0 (P10-T010): Regelpakete aus einem GitHub-Index, signiert, als Daten.

Ein Paket ist ein kanonisches JSON-Dokument (``ruttla-hub-package/0``) mit
seinen Regeltexten. Die CI des Index-Repos prüft es (Konformitäts-Kit +
Falsch-Positiv-Lauf), signiert die Bytes mit Sigstore und legt sie als Asset am
Release ``index`` ab. Der Client lädt über direkte Download-Adressen (keine
API), prüft Signatur und Hash und hält beides im Lockfile fest.

Sicherheitsgrenzen:

* Der Hub liefert nur Daten. Regeln laufen in der Engine (linearzeitig),
  Python-Plugins sind über den Hub nicht installierbar.
* Netz nur in ``ruttla hub search|add|sync``. Ein Scan liest das Paket aus
  ``.ruttla/hub/<name>/package.json`` und lädt es nur, wenn sein Hash dem
  Lockfile entspricht; sonst Abbruch (Exit 3).
* Ohne ``sigstore`` bricht ``add``/``sync`` ab — nie ungeprüft installiert.
* Hub-Regel-IDs tragen den Namensraum ``hub.<paket>.`` — eine Kollision mit
  einer offiziellen Regel oder einem anderen Paket ist damit ausgeschlossen,
  auch wenn eine spätere offizielle Regel denselben Kurznamen bekommt.

Der Lockfile-Hash schützt vor Übertragungsfehlern und Handänderungen am
installierten Paket. Gegen ein böswilliges Prüfziel schützt er nicht — wer das
Repo schreibt, schreibt auch das Lockfile. Was ein solches Paket anrichten kann,
begrenzt die Bauform: Daten, linearzeitige Muster, nur zusätzliche Befunde.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import re
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path

from .engine import EXIT_CRASH, EXIT_FAILED, EXIT_OK, EXIT_UNMEASURED
from .update import REPO, externally_managed

PACKAGE_FORMAT = "ruttla-hub-package/0"
INDEX_FORMAT = "ruttla-hub-index/0"
LOCK_FORMAT = "ruttla-hub-lock/0"
LOCKFILE = "ruttla-hub.lock"
STORE = Path(".ruttla") / "hub"
PACKAGE_FILE = "package.json"
BUNDLE_SUFFIX = ".sigstore.json"

# Derselbe Besitzer wie das Release-Repo — eine Quelle für den Namen.
HUB_REPO = REPO.split("/")[0] + "/ruttla-hub"
INDEX_BASE = f"https://github.com/{HUB_REPO}/releases/download/index/"
INDEX_FILE = "index.json"
# Wer signieren darf: genau der Veröffentlichungs-Workflow auf main.
SIGNER_IDENTITY = f"https://github.com/{HUB_REPO}/.github/workflows/publish.yml@refs/heads/main"
SIGNER_ISSUER = "https://token.actions.githubusercontent.com"
SIGSTORE_REQUIREMENT = "sigstore>=4.5,<5"

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
VERSION_RE = re.compile(r"^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$")
PACKAGE_KEYS = {"format", "name", "version", "description", "evidence", "license", "rules"}
MAX_DESCRIPTION = 300
MAX_RULES = 50


class HubError(Exception):
    """Hub-Vorgang abgebrochen; die Meldung sagt, was zu tun ist."""


# ---------------------------------------------------------------------------
# Paketformat
# ---------------------------------------------------------------------------

def canonical(pkg: dict) -> bytes:
    """Die eine Byte-Form eines Pakets: Hash und Signatur gelten genau ihr."""
    return json.dumps(pkg, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rule_path_re(name: str) -> re.Pattern[str]:
    return re.compile(rf"^([a-z0-9_]+)/(hub\.{re.escape(name)}\.[a-z0-9_]+(?:\.[a-z0-9_]+)*)\.toml$")


def validate_package(pkg: object) -> list[str]:
    """Alle Fehler gesammelt; das Regelschema selbst prüft die Engine."""
    if not isinstance(pkg, dict):
        return ["Paket ist kein JSON-Objekt"]
    errors: list[str] = []
    if set(pkg) != PACKAGE_KEYS:
        errors.append(f"Schlüssel müssen genau {sorted(PACKAGE_KEYS)} sein, sind {sorted(pkg)}")
    if pkg.get("format") != PACKAGE_FORMAT:
        errors.append(f"format muss {PACKAGE_FORMAT!r} sein")
    name = pkg.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        errors.append(f"name {name!r}: [a-z][a-z0-9_]{{1,39}}")
        name = None
    version = pkg.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        errors.append(f"version {version!r}: MAJOR.MINOR.PATCH")
    desc = pkg.get("description")
    if not isinstance(desc, str) or not desc.strip() or len(desc) > MAX_DESCRIPTION:
        errors.append(f"description: 1–{MAX_DESCRIPTION} Zeichen")
    evidence = pkg.get("evidence")
    if (not isinstance(evidence, list) or not evidence
            or not all(isinstance(e, str) and e.startswith("https://") for e in evidence)):
        errors.append("evidence: mindestens eine https-URL auf den belegten Fehlerfall")
    lic = pkg.get("license")
    if not isinstance(lic, str) or not lic.strip():
        errors.append("license: SPDX-Bezeichner fehlt")
    rules = pkg.get("rules")
    if not isinstance(rules, dict) or not rules:
        errors.append("rules: mindestens eine Regel")
        return errors
    if len(rules) > MAX_RULES:
        errors.append(f"rules: höchstens {MAX_RULES} Regeln je Paket")
    if name is None:
        return errors
    path_re = _rule_path_re(name)
    from .declarative import RULE_FORMAT

    for path, text in sorted(rules.items()):
        m = path_re.match(path) if isinstance(path, str) else None
        if m is None:
            errors.append(f"{path!r}: Pfad muss <plattform>/hub.{name}.<regel>.toml sein")
            continue
        if not isinstance(text, str):
            errors.append(f"{path}: Regeltext ist kein String")
            continue
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"{path}: kein TOML: {exc}")
            continue
        if data.get("format") != RULE_FORMAT:
            errors.append(f"{path}: format muss {RULE_FORMAT!r} sein")
        if data.get("id") != m.group(2):
            errors.append(f"{path}: id {data.get('id')!r} ≠ Dateiname")
        if data.get("platform") != m.group(1):
            errors.append(f"{path}: platform {data.get('platform')!r} ≠ Verzeichnis {m.group(1)!r}")
    return errors


def parse_package(raw: bytes) -> dict:
    """Bytes → geprüftes Paket. Nicht-kanonische Bytes sind abgelehnt: sonst
    hätte ein Inhalt mehrere Hashes, und das Lockfile wäre keine Aussage."""
    try:
        pkg = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubError(f"Paket ist kein JSON: {exc}") from exc
    errors = validate_package(pkg)
    if errors:
        raise HubError("Paket ungültig:\n  " + "\n  ".join(errors))
    if canonical(pkg) != raw:
        raise HubError("Paket ist nicht in kanonischer Form")
    return pkg


def read_source(directory: Path) -> dict:
    """Quellform im Index-Repo: ``package.toml`` + ``rules/<plattform>/<id>.toml``."""
    meta_path = directory / "package.toml"
    try:
        meta = tomllib.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HubError(f"{meta_path}: nicht lesbar: {exc}") from exc
    rules_root = directory / "rules"
    rules: dict[str, str] = {}
    if rules_root.is_dir():
        for p in sorted(rules_root.rglob("*")):
            if p.is_file():
                # Rohtext: der Hash gilt den Bytes, die der Autor eingereicht hat.
                try:
                    rules[p.relative_to(rules_root).as_posix()] = p.read_bytes().decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise HubError(f"{p}: kein UTF-8: {exc}") from exc
    pkg = {**meta, "rules": rules}
    errors = validate_package(pkg)
    if errors:
        raise HubError(f"{directory.name}: Paket ungültig:\n  " + "\n  ".join(errors))
    return pkg


def materialize(pkg: dict, dest: Path) -> None:
    """Regeln eines geprüften Pakets als Dateien für ``--rules``. Die Pfade
    sind durch ``validate_package`` auf ``<plattform>/<id>.toml`` beschränkt."""
    for rel, text in pkg["rules"].items():
        target = dest.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# Signatur
# ---------------------------------------------------------------------------

def sigstore_install_hint(executable: str, externally_managed: bool) -> str:
    """Installationshinweis, der auf diesem Python auch tatsächlich durchläuft."""
    plain = f"  {executable} -m pip install '{SIGSTORE_REQUIREMENT}'"
    if not externally_managed:
        return plain
    return (
        f"  {executable} ist systemverwaltet (PEP 668) — pip lehnt die Installation dort ab.\n"
        "  Entweder ruttla in einer venv mit dem Extra installieren (pip install 'ruttla[hub]'),\n"
        f"  oder bewusst ins System: {executable} -m pip install --break-system-packages "
        f"'{SIGSTORE_REQUIREMENT}'"
    )


def verify_signature(raw: bytes, bundle_raw: bytes | None) -> None:
    """Sigstore-Nachrichtensignatur des Index-Workflows; jede Abweichung bricht ab."""
    if bundle_raw is None:
        raise HubError("Paket ist nicht signiert (kein Sigstore-Bundle) — abgelehnt.")
    try:
        from sigstore.errors import Error as SigstoreError
        from sigstore.models import Bundle
        from sigstore.verify import Verifier, policy
    except ImportError as exc:
        raise HubError(
            "Signaturprüfung braucht sigstore — ohne Prüfung wird nichts installiert:\n"
            + sigstore_install_hint(sys.executable, externally_managed())
        ) from exc
    try:
        bundle = Bundle.from_json(bundle_raw)
        Verifier.production().verify_artifact(
            input_=raw, bundle=bundle,
            policy=policy.Identity(identity=SIGNER_IDENTITY, issuer=SIGNER_ISSUER),
        )
    except (SigstoreError, ValueError) as exc:
        raise HubError(f"Signatur ungültig — abgelehnt: {exc}") from exc


# ---------------------------------------------------------------------------
# Netz (nur hub-Befehle)
# ---------------------------------------------------------------------------

def _fetch(name: str) -> bytes | None:
    """Asset am Release ``index``; None bei 404."""
    import urllib.error

    from .update import _get

    try:
        return _get(INDEX_BASE + name)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise HubError(f"Hub nicht lesbar ({name}): {exc}") from exc
    except OSError as exc:
        raise HubError(f"Hub nicht lesbar ({name}): {exc}") from exc


def fetch_index() -> dict:
    raw = _fetch(INDEX_FILE)
    if raw is None:
        raise HubError(f"Kein Index unter {INDEX_BASE}{INDEX_FILE}")
    try:
        index = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubError(f"Index ist kein JSON: {exc}") from exc
    if not isinstance(index, dict) or index.get("format") != INDEX_FORMAT \
            or not isinstance(index.get("packages"), dict):
        raise HubError(f"Index hat nicht das Format {INDEX_FORMAT}")
    return index


def entry_ok(entry: object) -> bool:
    """Index- oder Lockfile-Eintrag: gültige Version und sha256 — beide landen in URL und Vergleich."""
    return (isinstance(entry, dict)
            and isinstance(entry.get("version"), str) and bool(VERSION_RE.match(entry["version"]))
            and isinstance(entry.get("sha256"), str) and bool(re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])))


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def package_file(name: str, version: str) -> str:
    return f"{name}-{version}.json"


def download(name: str, version: str, expected_sha: str) -> tuple[bytes, bytes]:
    """Paket + Bundle laden, Hash und Signatur prüfen; erst dann zurückgeben."""
    fname = package_file(name, version)
    raw = _fetch(fname)
    if raw is None:
        raise HubError(f"{fname} fehlt im Hub")
    actual = sha256(raw)
    if actual != expected_sha:
        raise HubError(f"{fname}: Hash {actual[:12]}… ≠ erwartet {expected_sha[:12]}… — abgelehnt")
    bundle = _fetch(fname + BUNDLE_SUFFIX)
    verify_signature(raw, bundle)
    pkg = parse_package(raw)
    if pkg["name"] != name or pkg["version"] != version:
        raise HubError(f"{fname}: enthält {pkg['name']} {pkg['version']}")
    return raw, bundle  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Lockfile und Ablage im Projekt
# ---------------------------------------------------------------------------

def read_lock(root: Path) -> dict[str, dict[str, str]]:
    path = _inside(root, LOCKFILE)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubError(f"{LOCKFILE}: nicht lesbar: {exc}") from exc
    pkgs = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("format") != LOCK_FORMAT or not isinstance(pkgs, dict):
        raise HubError(f"{LOCKFILE}: kein {LOCK_FORMAT}")
    for name, entry in pkgs.items():
        if not NAME_RE.match(name) or not entry_ok(entry):
            raise HubError(f"{LOCKFILE}: Eintrag {name!r} ungültig")
    return pkgs


def write_lock(root: Path, pkgs: dict[str, dict[str, str]]) -> None:
    path = _inside(root, LOCKFILE)
    if not pkgs:
        path.unlink(missing_ok=True)
        return
    data = {"format": LOCK_FORMAT,
            "packages": {n: {"version": e["version"], "sha256": e["sha256"]} for n, e in sorted(pkgs.items())}}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _inside(root: Path, *parts: str) -> Path:
    """Pfad im Projekt, ohne symbolischen Link oder Junction auf dem Weg.
    Sonst schreibt ``add``/``sync`` über einen Link im Prüfziel außerhalb des
    Projekts, und ``remove`` löscht dort."""
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise HubError(f"{path} ist ein symbolischer Link — abgebrochen")
    if not path.resolve().is_relative_to(root.resolve()):
        raise HubError(f"{path} liegt außerhalb von {root}")
    return path


def _store(root: Path, name: str, *file: str) -> Path:
    return _inside(root, *STORE.parts, name, *file)


def _install(root: Path, raw: bytes, bundle: bytes) -> None:
    pkg = parse_package(raw)
    _store(root, pkg["name"]).mkdir(parents=True, exist_ok=True)
    _store(root, pkg["name"], PACKAGE_FILE + BUNDLE_SUFFIX).write_bytes(bundle)
    _store(root, pkg["name"], PACKAGE_FILE).write_bytes(raw)


def _official_ids() -> set[str]:
    from .engine import load_checks
    from .registry import REGISTRY

    if not REGISTRY:
        load_checks()
    return set(REGISTRY)


def _collisions(pkg: dict, taken: set[str]) -> list[str]:
    ids = [Path(rel).stem for rel in pkg["rules"]]
    return sorted(i for i in ids if i in taken)


def add(root: Path, name: str) -> str:
    index = fetch_index()
    entry = index["packages"].get(name)
    if entry is None:
        raise HubError(f"Paket {name!r} steht nicht im Index")
    if not entry_ok(entry):
        raise HubError(f"Index-Eintrag {name!r} ungültig (version/sha256)")
    version, expected = entry["version"], entry["sha256"]
    raw, bundle = download(name, version, expected)
    clash = _collisions(parse_package(raw), _official_ids())
    if clash:
        raise HubError(f"ID-Kollision mit offiziellen Checks: {', '.join(clash)}")
    lock = read_lock(root)
    _install(root, raw, bundle)
    lock[name] = {"version": version, "sha256": expected}
    write_lock(root, lock)
    return f"{name} {version} installiert ({expected[:12]}…), signiert von {SIGNER_IDENTITY}"


def sync(root: Path) -> list[str]:
    """Stellt genau den Stand des Lockfiles her — lädt nur, was fehlt oder abweicht."""
    out = []
    for name, entry in sorted(read_lock(root).items()):
        local = _store(root, name, PACKAGE_FILE)
        if local.is_file() and sha256(local.read_bytes()) == entry["sha256"]:
            out.append(f"{name} {entry['version']}: aktuell")
            continue
        raw, bundle = download(name, entry["version"], entry["sha256"])
        _install(root, raw, bundle)
        out.append(f"{name} {entry['version']}: geladen und geprüft")
    return out


def remove(root: Path, name: str) -> str:
    lock = read_lock(root)
    if name not in lock or not NAME_RE.match(name):
        raise HubError(f"{name!r} ist nicht installiert")
    store = _store(root, name)  # Link-Prüfung vor jeder Änderung
    del lock[name]
    write_lock(root, lock)
    shutil.rmtree(store, ignore_errors=True)
    return f"{name} entfernt"


# ---------------------------------------------------------------------------
# Scan: installierte Pakete registrieren (offline)
# ---------------------------------------------------------------------------

def register_locked(root: Path) -> int:
    """Registriert die Regeln aller Pakete im Lockfile; Abweichung = HubError.
    Kein Netz: was nicht lokal und unverändert vorliegt, bricht den Scan ab."""
    from .declarative import EXTRA_RULE_DIRS, make_check
    from .registry import REGISTRY

    lock = read_lock(root)
    if not lock:
        return 0
    work = Path(tempfile.mkdtemp(prefix="ruttla-hub-"))
    atexit.register(shutil.rmtree, work, True)
    checks = []
    for name, entry in sorted(lock.items()):
        local = _store(root, name, PACKAGE_FILE)
        if not local.is_file():
            raise HubError(f"Hub-Paket {name} fehlt in {STORE.as_posix()}/ — `ruttla hub sync` ausführen")
        raw = local.read_bytes()
        if sha256(raw) != entry["sha256"]:
            raise HubError(f"Hub-Paket {name}: Hash weicht vom {LOCKFILE} ab — "
                           "verändert oder unvollständig; `ruttla hub sync` stellt den geprüften Stand her")
        pkg = parse_package(raw)
        if pkg["name"] != name or pkg["version"] != entry["version"]:
            raise HubError(f"Hub-Paket {name}: enthält {pkg['name']} {pkg['version']}, Lockfile sagt {entry['version']}")
        clash = _collisions(pkg, set(REGISTRY))
        if clash:
            raise HubError(f"Hub-Paket {name}: ID-Kollision mit {', '.join(clash)}")
        materialize(pkg, work)
        for text in pkg["rules"].values():
            rule = tomllib.loads(text)
            rule["tags"] = [*rule.get("tags", []), f"hub:{name}"]
            checks.append(make_check(rule))
    for check in checks:
        REGISTRY[check.id] = check
    EXTRA_RULE_DIRS.append(work)
    return len(checks)


# ---------------------------------------------------------------------------
# Index-CI: prüfen und bauen
# ---------------------------------------------------------------------------

def false_positive_scan(rules: Path, corpus: list[Path]) -> tuple[int, list[str]]:
    """Scan der Paketregeln über den Gesund-Korpus. Schwelle: null Befunde.
    Eine Regel, die im ganzen Korpus keine Datei geprüft hat, ist dort nicht
    gemessen — nie bestanden."""
    from .declarative import find_engine
    from .rulekit import SELFTEST_TIMEOUT_S, _json, _run_engine

    binary = find_engine()
    if binary is None:
        return EXIT_UNMEASURED, ["ruttla-engine fehlt — Falsch-Positiv-Lauf nicht gemessen"]
    if not corpus:
        return EXIT_UNMEASURED, ["kein Gesund-Korpus angegeben — Falsch-Positiv-Lauf nicht gemessen"]
    examined: dict[str, int] = {}
    hits: list[str] = []
    for root in corpus:
        if not root.is_dir():
            return EXIT_CRASH, [f"Korpus {root} ist kein Verzeichnis"]
        code, raw, _ = _run_engine(binary, ["scan", str(root), "--rules", str(rules),
                                            "--view", "unscoped"], SELFTEST_TIMEOUT_S * 5)
        data = _json(raw)
        if code != 0 or "results" not in data:
            detail = data.get("error", {}).get("message", "") if code is not None else "Zeitlimit"
            return EXIT_CRASH, [f"Engine-Lauf über {root.name} gescheitert: {detail}"]
        for res in data["results"]:
            examined[res["check_id"]] = examined.get(res["check_id"], 0) + res["units_examined"]
            for f in res["findings"]:
                hits.append(f"{res['check_id']}: {root.name}/{f['file']}:{f['line']}: {f['evidence']}")
    lines = [f"{rid}: {n} Dateien im Korpus geprüft" for rid, n in sorted(examined.items())]
    if hits:
        return EXIT_FAILED, lines + [f"{len(hits)} Befunde im Gesund-Korpus (Schwelle 0):"] + hits[:20]
    unmeasured = sorted(rid for rid, n in examined.items() if n == 0)
    if unmeasured:
        return EXIT_UNMEASURED, lines + [f"im Korpus nicht gemessen: {', '.join(unmeasured)}"]
    return EXIT_OK, lines


def check_source(directory: Path, corpus: list[Path]) -> tuple[int, list[str]]:
    """Aufnahmeprüfung eines Pakets: Format · Konformitäts-Kit · Falsch-Positiv-Lauf.
    Alle drei laufen, auch wenn einer ablehnt — ein Rot verdeckt nie das nächste."""
    from .rulekit import _text, exit_code, run_kit

    try:
        pkg = read_source(directory)
    except HubError as exc:
        return EXIT_FAILED, [f"format: abgelehnt — {exc}"]
    lines = [f"format: {pkg['name']} {pkg['version']}, {len(pkg['rules'])} Regel(n)"]
    clash = _collisions(pkg, _official_ids())
    codes = [EXIT_FAILED if clash else EXIT_OK]
    if clash:
        lines.append(f"id: Kollision mit offiziellen Checks: {', '.join(clash)}")
    reports = run_kit([directory / "rules"])
    codes.append(exit_code(reports))
    lines.append("kit:\n" + _text(reports).rstrip())
    with tempfile.TemporaryDirectory(prefix="ruttla-hub-check-") as tmp:
        materialize(pkg, Path(tmp))
        code, fp = false_positive_scan(Path(tmp), corpus)
    codes.append(code)
    lines.append("falsch-positiv:\n  " + "\n  ".join(fp))
    worst = max(codes, key=lambda c: (EXIT_OK, EXIT_UNMEASURED, EXIT_FAILED, EXIT_CRASH).index(c))
    return worst, lines


def build_index(packages: Path, out: Path, previous: dict | None) -> list[str]:
    """Kanonische Paketdateien + ``index.json``. Eine veröffentlichte Version
    ist unveränderlich: gleicher Name und gleiche Version mit anderem Inhalt
    bricht ab (sonst würde jedes Lockfile mit dieser Version rot)."""
    prev = {} if previous is None else previous.get("packages") if isinstance(previous, dict) else None
    if not isinstance(prev, dict) or not all(isinstance(e, dict) and entry_ok(e)
                                             and isinstance(e.get("versions", {}), dict)
                                             for e in prev.values()):
        raise HubError(f"bisheriger Index hat nicht das Format {INDEX_FORMAT}")
    out.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    for name, entry in prev.items():
        index[name] = {**entry, "versions": dict(entry.get("versions", {}))}
    written = []
    dirs = sorted(d for d in packages.iterdir() if (d / "package.toml").is_file())
    if not dirs:
        raise HubError(f"keine Pakete unter {packages}")
    for d in dirs:
        pkg = read_source(d)
        if d.name != pkg["name"]:
            raise HubError(f"{d}: Verzeichnisname ≠ name {pkg['name']!r}")
        raw = canonical(pkg)
        digest = sha256(raw)
        entry = index.setdefault(pkg["name"], {"versions": {}})
        latest = entry.get("version")
        if latest is not None and version_key(pkg["version"]) < version_key(latest):
            raise HubError(f"{pkg['name']} {pkg['version']} ist älter als die veröffentlichte {latest} "
                           "— ein Rückbau ist eine neue, höhere Version")
        known = entry["versions"].get(pkg["version"])
        if known is not None and known != digest:
            raise HubError(f"{pkg['name']} {pkg['version']} ist schon mit anderem Inhalt veröffentlicht "
                           "— Version erhöhen")
        entry["versions"][pkg["version"]] = digest
        entry.update(version=pkg["version"], sha256=digest, description=pkg["description"])
        (out / package_file(pkg["name"], pkg["version"])).write_bytes(raw)
        written.append(package_file(pkg["name"], pkg["version"]))
    doc = {"format": INDEX_FORMAT, "packages": {n: index[n] for n in sorted(index)}}
    (out / INDEX_FILE).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class HubArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_CRASH, f"RUNNER_ERROR\tinvalid_arguments\t{message}\n")


def build_parser(prog: str) -> HubArgumentParser:
    parser = HubArgumentParser(prog=f"{prog} hub", description=(
        "Regelpakete aus dem Gate-Hub. Netz nur in search/add/sync; Scans bleiben offline."))
    sub = parser.add_subparsers(dest="cmd", required=True, parser_class=HubArgumentParser)
    s = sub.add_parser("search", help="Index durchsuchen")
    s.add_argument("text", nargs="?", default="")
    for cmd, helptext in (("add", "Paket installieren (Signatur + Hash, Lockfile)"),
                          ("remove", "Paket entfernen")):
        p = sub.add_parser(cmd, help=helptext)
        p.add_argument("name")
        p.add_argument("--root", default=".")
    p = sub.add_parser("sync", help="Stand des Lockfiles herstellen")
    p.add_argument("--root", default=".")
    p = sub.add_parser("check", help="Aufnahmeprüfung eines Paketverzeichnisses (Index-CI)")
    p.add_argument("package", type=Path)
    p.add_argument("--corpus", type=Path, action="append", default=[], help="Gesund-Korpus (mehrfach)")
    p = sub.add_parser("build", help="Kanonische Pakete + index.json bauen (Index-CI)")
    p.add_argument("packages", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--previous", type=Path, help="bisher veröffentlichter index.json")
    return parser


def run_hub_command(argv: list[str], prog: str = "ruttla") -> int:
    args = build_parser(prog).parse_args(argv)
    try:
        if args.cmd == "search":
            pkgs = fetch_index()["packages"]
            needle = args.text.lower()
            hits = [(n, e) for n, e in sorted(pkgs.items())
                    if isinstance(e, dict)
                    and (needle in n or needle in str(e.get("description", "")).lower())]
            for n, e in hits:
                print(f"{n} {e.get('version')}\t{e.get('description', '')}")
            return EXIT_OK if hits else EXIT_FAILED
        if args.cmd == "check":
            code, lines = check_source(args.package, args.corpus)
            print("\n".join(lines))
            print({EXIT_OK: "ANGENOMMEN", EXIT_FAILED: "ABGELEHNT",
                   EXIT_UNMEASURED: "NICHT GEMESSEN"}.get(code, "FEHLER"))
            return code
        if args.cmd == "build":
            previous = None
            if args.previous is not None:
                try:
                    previous = json.loads(args.previous.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise HubError(f"{args.previous}: nicht lesbar: {exc}") from exc
            for f in build_index(args.packages, args.out, previous):
                print(f)
            return EXIT_OK
        root = Path(args.root).resolve()
        if not root.is_dir():
            raise HubError(f"Kein Verzeichnis: {root}")
        if args.cmd == "add":
            print(add(root, args.name))
        elif args.cmd == "remove":
            print(remove(root, args.name))
        else:
            print("\n".join(sync(root)) or f"{LOCKFILE}: keine Pakete")
        return EXIT_OK
    except HubError as exc:
        print(f"RUNNER_ERROR\thub\t{exc}", file=sys.stderr)
        return EXIT_CRASH
