"""Single source of truth for platforms (P01-T007, P10-T002).

Alle Erkennungssignale stehen in ``platforms.toml``. Dieses Modul lädt und
validiert das Manifest und leitet daraus ab:

* ``PACK_PLATFORMS`` — platforms that own an official rule pack. Only these
  are valid for ``--platform`` and ``project.platform``.
* ``PLATFORMS_WITHOUT_PACK`` — detected and reported, but no rules exist yet.
  They must never look like "measured" (R-011).

Detection measures technical PROPERTIES of the project, never folder or
project names.
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .discovery import SourceFile

MANIFEST_VERSION = 1
_PLATFORM_KEYS = {"pack", "always", "extensions", "file_names", "file_suffixes",
                  "dir_suffixes", "content", "requires", "root_markers", "claims"}
_CONTENT_KEYS = {"extensions", "pattern", "examples", "counter_examples"}


class ManifestError(ValueError):
    """Das Erkennungsmanifest ist ungültig — kein stiller Rückfall."""


@dataclass(frozen=True)
class ContentSignal:
    extensions: tuple[str, ...]
    pattern: re.Pattern


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    pack: bool
    always: bool
    extensions: frozenset[str]
    file_names: frozenset[str]
    file_suffixes: tuple[str, ...]
    dir_suffixes: tuple[str, ...]
    content: tuple[ContentSignal, ...]
    requires: tuple[str, ...]
    root_markers: tuple[tuple[str, ...], ...] = ()
    claims: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ProjectRoot:
    """Ein Teilprojekt: Wurzelordner (relativ, "." = Prüfwurzel), Plattform und
    die Marker-Datei, an der es erkannt wurde."""
    path: str
    platform: str
    marker: str

    def to_dict(self) -> dict:
        return {"path": self.path, "platform": self.platform, "marker": self.marker}

    def contains(self, rel: str) -> bool:
        return self.path == "." or rel.startswith(self.path + "/")


def _strings(where: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ManifestError(f"{where} muss eine Liste nicht-leerer Strings sein.")
    return tuple(value)


def _content(name: str, i: int, raw: object) -> ContentSignal:
    where = f"platforms.{name}.content[{i}]"
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} muss eine Tabelle sein.")
    unknown = set(raw) - _CONTENT_KEYS
    if unknown:
        raise ManifestError(f"{where}: unbekannte Schlüssel {sorted(unknown)}")
    pattern_text = raw.get("pattern")
    if not isinstance(pattern_text, str) or not pattern_text:
        raise ManifestError(f"{where}.pattern fehlt.")
    try:
        pattern = re.compile(pattern_text, re.MULTILINE)
    except re.error as exc:
        raise ManifestError(f"{where}.pattern ungültig: {exc}") from exc
    examples = _strings(f"{where}.examples", raw.get("examples"))
    counter = _strings(f"{where}.counter_examples", raw.get("counter_examples"))
    # Ein Muster ohne geprüfte Beispiele ist eine Vermutung: beide Richtungen
    # werden bei jedem Laden gemessen, nicht erst im Test.
    for ex in examples:
        if not pattern.search(ex):
            raise ManifestError(f"{where}: Beispiel trifft nicht: {ex!r}")
    for ex in counter:
        if pattern.search(ex):
            raise ManifestError(f"{where}: Gegenbeispiel trifft: {ex!r}")
    exts = _strings(f"{where}.extensions", raw.get("extensions"))
    return ContentSignal(tuple(e.lower() for e in exts), pattern)


def _marker(name: str, text: str) -> tuple[str, ...]:
    segments = tuple(text.split("/"))
    if any(not s or s in (".", "..") for s in segments):
        raise ManifestError(f"platforms.{name}.root_markers: ungültiger Pfad {text!r}")
    return segments


def parse_manifest(data: dict) -> dict[str, PlatformSpec]:
    if data.get("manifest_version") != MANIFEST_VERSION:
        raise ManifestError(f"manifest_version muss {MANIFEST_VERSION} sein.")
    unknown_top = set(data) - {"manifest_version", "platforms"}
    if unknown_top:
        raise ManifestError(f"Unbekannte Schlüssel: {sorted(unknown_top)}")
    platforms = data.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        raise ManifestError("Null Plattformen im Manifest — die Erkennung prüft nichts.")
    specs: dict[str, PlatformSpec] = {}
    for name, raw in platforms.items():
        if not isinstance(raw, dict):
            raise ManifestError(f"platforms.{name} muss eine Tabelle sein.")
        unknown = set(raw) - _PLATFORM_KEYS
        if unknown:
            raise ManifestError(f"platforms.{name}: unbekannte Schlüssel {sorted(unknown)}")
        pack = raw.get("pack")
        if not isinstance(pack, bool):
            raise ManifestError(f"platforms.{name}.pack muss true oder false sein.")
        always = raw.get("always", False)
        content_raw = raw.get("content", [])
        if not isinstance(content_raw, list):
            raise ManifestError(f"platforms.{name}.content muss eine Liste sein.")
        spec = PlatformSpec(
            name=name, pack=pack, always=bool(always),
            extensions=frozenset(e.lower() for e in _strings(
                f"platforms.{name}.extensions", raw.get("extensions", []))),
            file_names=frozenset(n.lower() for n in _strings(
                f"platforms.{name}.file_names", raw.get("file_names", []))),
            file_suffixes=_strings(f"platforms.{name}.file_suffixes",
                                   raw.get("file_suffixes", [])),
            dir_suffixes=_strings(f"platforms.{name}.dir_suffixes",
                                  raw.get("dir_suffixes", [])),
            content=tuple(_content(name, i, c) for i, c in enumerate(content_raw)),
            requires=_strings(f"platforms.{name}.requires", raw.get("requires", [])),
            root_markers=tuple(_marker(name, m) for m in _strings(
                f"platforms.{name}.root_markers", raw.get("root_markers", []))),
            claims=frozenset(e.lower() for e in _strings(
                f"platforms.{name}.claims", raw.get("claims", []))),
        )
        if spec.claims and not spec.root_markers:
            raise ManifestError(f"platforms.{name}.claims braucht root_markers — "
                                "ohne Wurzel gälte der Anspruch fürs ganze Repo.")
        has_signal = (spec.extensions or spec.file_names or spec.file_suffixes
                      or spec.dir_suffixes or spec.content or spec.root_markers)
        if not spec.always and not has_signal:
            raise ManifestError(f"platforms.{name}: kein einziges Erkennungssignal.")
        specs[name] = spec
    for spec in specs.values():
        for dep in spec.requires:
            if dep not in specs:
                raise ManifestError(f"platforms.{spec.name}.requires: unbekannt {dep!r}")
    return specs


def load_manifest() -> dict[str, PlatformSpec]:
    text = resources.files(__package__).joinpath("platforms.toml").read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"platforms.toml ist kein gültiges TOML: {exc}") from exc
    return parse_manifest(data)


MANIFEST: dict[str, PlatformSpec] = load_manifest()

PACK_PLATFORMS: tuple[str, ...] = tuple(n for n, s in MANIFEST.items() if s.pack)
PLATFORMS_WITHOUT_PACK: tuple[str, ...] = tuple(n for n, s in MANIFEST.items() if not s.pack)
KNOWN_PLATFORMS: tuple[str, ...] = PACK_PLATFORMS + PLATFORMS_WITHOUT_PACK


def _match_marker(segments: tuple[str, ...], rel: str) -> str | None:
    """Wurzelpfad, falls ``rel`` auf den Marker endet, sonst None."""
    parts = rel.split("/")
    k = len(segments)
    if len(parts) < k:
        return None
    if all(fnmatch.fnmatchcase(p, s) for p, s in zip(parts[-k:], segments)):
        return "/".join(parts[:-k]) or "."
    return None


def find_roots(files: list["SourceFile"]) -> list[ProjectRoot]:
    """Alle Projektwurzeln, sortiert nach Pfad und Plattform."""
    roots: dict[tuple[str, str], ProjectRoot] = {}
    for name, spec in MANIFEST.items():
        if not spec.root_markers:
            continue
        for f in files:
            for segments in spec.root_markers:
                path = _match_marker(segments, f.rel)
                if path is not None and (path, name) not in roots:
                    roots[(path, name)] = ProjectRoot(path, name, f.rel)
    return sorted(roots.values(), key=lambda r: (r.path, r.platform))


def claimed_files(files: list["SourceFile"], roots: list[ProjectRoot]) -> dict[str, str]:
    """rel → Plattform, der die Datei innerhalb ihrer Wurzel gehört. Bei
    verschachtelten Wurzeln gewinnt die innerste."""
    owners: dict[str, str] = {}
    claiming = [r for r in roots if MANIFEST[r.platform].claims]
    claiming.sort(key=lambda r: (0 if r.path == "." else r.path.count("/") + 1))
    for root in claiming:
        claims = MANIFEST[root.platform].claims
        for f in files:
            if f.ext in claims and root.contains(f.rel):
                owners[f.rel] = root.platform
    return owners


def content_patterns(platform: str) -> tuple[re.Pattern, ...]:
    """Inhaltsmuster einer Plattform — für Checks, die dasselbe Merkmal brauchen
    wie die Erkennung (z. B. Hardware-Importe im Raspberry-Pack)."""
    return tuple(c.pattern for c in MANIFEST[platform].content)


def platform_present(ctx: "Context", name: str) -> bool:
    """Greift mindestens ein Signal dieser Plattform? ``requires`` wird hier
    NICHT ausgewertet — das macht ``detect_platforms``."""
    spec = MANIFEST[name]
    if spec.always:
        return True
    ctx = ctx.scoped(name)
    files = ctx.all_files()
    for f in files:
        if f.ext in spec.extensions:
            return True
        if spec.file_names and f.rel.rsplit("/", 1)[-1].lower() in spec.file_names:
            return True
        if spec.file_suffixes and f.rel.endswith(spec.file_suffixes):
            return True
        if any(_match_marker(m, f.rel) is not None for m in spec.root_markers):
            return True
    for suffix in spec.dir_suffixes:
        if ctx.dirs_with_suffix(suffix):
            return True
    for signal in spec.content:
        for f in ctx.files(*signal.extensions):
            if signal.pattern.search(f.text):
                return True
    return False


def detect_platforms(ctx: "Context") -> set[str]:
    """Erkennt Plattformen an EIGENSCHAFTEN des Projekts, nicht an Namen."""
    found: set[str] = set()
    pending = list(MANIFEST)
    # requires kann auf eine später definierte Plattform zeigen: so lange
    # nachziehen, bis sich nichts mehr ändert.
    while True:
        progressed = False
        for name in list(pending):
            spec = MANIFEST[name]
            if any(dep not in found for dep in spec.requires):
                continue
            pending.remove(name)
            progressed = True
            if platform_present(ctx, name):
                found.add(name)
        if not progressed:
            return found
