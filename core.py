#!/usr/bin/env python3
"""
Kern der Quality-Gate-Engine: Ergebnistypen, Registry, Datei-Discovery, Kontext.

Zentrale Bauformentscheidungen (aus den Guidelines abgeleitet):

* DREI Ausgänge je Check: PASS / FAIL / UNMEASURED. "Nicht gemessen" ist ein
  eigener Zustand, nie stillschweigend grün. Ein Check, der seine Eingabe nicht
  herstellen konnte, meldet UNMEASURED mit Begründung.
* Jeder Befund trägt eine stabile ID (`brand.hardcoded_name`), Datei, Zeile,
  Beleg und einen Fix-Hinweis. Die ID ist der Vertrag für jede CLI — kein
  Anzeigetext wird je zum Anker.
* Checks prüfen EIGENSCHAFTEN, nicht Bauformen. Wo ein Check eine konkrete
  Bauart verlangt, ist das im Docstring des Checks ausdrücklich begründet.
* Jeder Check bringt seine eigenen Sabotage-Proben mit (`self_test`), damit
  "ein Gate, das nie rot war" nicht vorkommen kann.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Callable, Iterable, Iterator, Sequence

SCHEMA_VERSION = "1.0"


class GateInputError(RuntimeError):
    """Die Eingabe konnte nicht zuverlässig gelesen oder bestimmt werden."""


class ConfigError(GateInputError):
    """Das Gate-Profil ist vorhanden, aber ungültig oder nicht lesbar."""


class ChangedFilesError(GateInputError):
    """Die geänderten Dateien konnten nicht sicher bestimmt werden."""


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNMEASURED = "unmeasured"
    ERROR = "error"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    """Ein einzelner Befund. `check_id` + `file` + `line` identifizieren ihn."""

    check_id: str
    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None
    evidence: str | None = None
    fix: str | None = None
    guideline: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class CheckResult:
    check_id: str
    status: Status
    title: str
    findings: list[Finding] = field(default_factory=list)
    # Warum nicht gemessen wurde — Pflicht bei UNMEASURED, sonst ist der
    # dritte Ausgang wertlos.
    reason: str | None = None
    # Was der Check tatsächlich angefasst hat. Null Einheiten bei einem
    # inhaltlichen Check ist verdächtig und wird vom Runner geprüft.
    units_examined: int = 0
    unit_label: str = "Dateien"
    platform: str = "universal"

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "status": self.status.value,
            "platform": self.platform,
            "reason": self.reason,
            "units_examined": self.units_examined,
            "unit_label": self.unit_label,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class SelfTestCase:
    """Eine Sabotage-Probe: Dateien anlegen, Check laufen lassen, Ausgang erwarten."""

    name: str
    files: dict[str, str]
    expect: Status
    # Wenn gesetzt: dieser Befund muss unter den Findings sein.
    expect_finding_contains: str | None = None


# ---------------------------------------------------------------------------
# Datei-Discovery
# ---------------------------------------------------------------------------

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "DerivedData", ".build", "build",
    "dist", ".next", ".nuxt", "out", "venv", ".venv", "env", "__pycache__",
    ".godot", ".import", "Pods", "Carthage", ".gradle", "target", "bin", "obj",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", ".turbo",
    "vendor", ".terraform", ".cache", "Library", "Temp", "addons",
    ".qualitygate-work", ".temp", ".tmp", "tmp", ".svelte-kit", ".astro",
    ".parcel-cache", ".angular", "__snapshots__", "migrations_backup",
    ".vercel", ".netlify", ".supabase", "storybook-static", ".docusaurus",
}

# Dateien, die per Definition über Regeln SPRECHEN statt sie zu verletzen.
# Sonst löst die Dokumentation eines Fehlers denselben Alarm aus wie der Fehler.
DEFAULT_EXCLUDE_FILES = {
    "CLAUDE.md", "AGENTS.md", "GEMINI.md", "HANDOVER.md", "README.md",
    "CHANGELOG.md", "ROADMAP.md", "MASTER_ROADMAP.md", ".qualitygate.toml",
}


@dataclass
class SourceFile:
    path: str          # absolut
    rel: str           # relativ zur Projektwurzel
    ext: str           # ".swift", kleingeschrieben
    _text: str | None = None
    _lines: list[str] | None = None

    @property
    def text(self) -> str:
        if self._text is None:
            try:
                with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                    self._text = fh.read()
            except OSError as exc:
                raise GateInputError(
                    f"Eingabedatei nicht lesbar: {self.rel}: {exc}"
                ) from exc
        return self._text

    @property
    def lines(self) -> list[str]:
        if self._lines is None:
            self._lines = self.text.splitlines()
        return self._lines

    def line_of(self, offset: int) -> int:
        """1-basierte Zeilennummer zu einem Zeichen-Offset im Text."""
        return self.text.count("\n", 0, offset) + 1


# Kommentar-Strippen: eine Mustersuche, die Kommentare mitliest, schlägt bei
# der Dokumentation eines Fehlers genauso an wie beim Fehler selbst.
_LINE_COMMENT = {
    ".swift": "//", ".ts": "//", ".tsx": "//", ".js": "//", ".jsx": "//",
    ".mjs": "//", ".cjs": "//", ".cs": "//", ".c": "//", ".h": "//",
    ".cpp": "//", ".hpp": "//", ".java": "//", ".kt": "//", ".go": "//",
    ".rs": "//", ".gd": "#", ".py": "#", ".ps1": "#", ".sh": "#", ".rb": "#", ".yaml": "#",
    ".yml": "#", ".toml": "#",
}
_BLOCK_COMMENTS = {
    ".swift": [("/*", "*/")], ".ts": [("/*", "*/")], ".tsx": [("/*", "*/")],
    ".js": [("/*", "*/")], ".jsx": [("/*", "*/")], ".mjs": [("/*", "*/")],
    ".cs": [("/*", "*/")], ".cpp": [("/*", "*/")], ".java": [("/*", "*/")],
    ".kt": [("/*", "*/")], ".go": [("/*", "*/")], ".rs": [("/*", "*/")],
    ".css": [("/*", "*/")], ".scss": [("/*", "*/")],
    ".html": [("<!--", "-->")], ".xml": [("<!--", "-->")],
    ".xaml": [("<!--", "-->")], ".vue": [("<!--", "-->"), ("/*", "*/")],
    ".svelte": [("<!--", "-->"), ("/*", "*/")],
    ".ps1": [("<#", "#>")],
}


def strip_comments(text: str, ext: str) -> str:
    """Ersetzt Kommentarinhalt durch Leerzeichen — Zeilennummern bleiben gültig.

    Bewusst konservativ: Zeichenketten werden respektiert, damit ein "//" in
    einer URL nicht den Rest der Zeile verschluckt.
    """
    line_marker = _LINE_COMMENT.get(ext)
    blocks = _BLOCK_COMMENTS.get(ext, [])
    if not line_marker and not blocks:
        return text

    out = list(text)
    i = 0
    n = len(text)
    in_string: str | None = None
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\" and in_string in "\"'`":
                i += 2
                continue
            if text.startswith(in_string, i):
                i += len(in_string)
                in_string = None
                continue
            i += 1
            continue
        # String-Beginn (nur für C-artige/Script-Sprachen sinnvoll)
        if ch in "\"'`" and ext not in (".html", ".xml", ".xaml"):
            in_string = ch
            i += 1
            continue
        # Blockkommentar
        matched_block = False
        for start, end in blocks:
            if text.startswith(start, i):
                stop = text.find(end, i + len(start))
                stop = n if stop == -1 else stop + len(end)
                for k in range(i, stop):
                    if out[k] != "\n":
                        out[k] = " "
                i = stop
                matched_block = True
                break
        if matched_block:
            continue
        # Zeilenkommentar
        if line_marker and text.startswith(line_marker, i):
            stop = text.find("\n", i)
            stop = n if stop == -1 else stop
            for k in range(i, stop):
                out[k] = " "
            i = stop
            continue
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Kontext
# ---------------------------------------------------------------------------

# Eine Datei, die Prüfmuster oder Sabotage-Testdaten ENTHÄLT, verletzt die
# Regeln nicht — sie beschreibt sie. Ohne diese Ausnahme meldet das Gate seine
# eigenen Testfälle als Befunde, und jedes Projekt, das eigene Gates mitführt,
# bekommt dieselben falschen Treffer. Gemessen wird die Eigenschaft "diese
# Datei definiert Prüfungen", nicht ein Pfadname.
_SELF_DESCRIBING = re.compile(
    r"(?:^|\n)\s*(?:@register\s*\(|SelfTestCase\s*\(|def\s+test_\w+|"
    r"class\s+Test\w+|describe\s*\(|it\s*\(\s*[\"'])"
)


def is_rule_definition_file(sf: "SourceFile") -> bool:
    """True für Dateien, die Prüfregeln oder Testfälle definieren."""
    return bool(_SELF_DESCRIBING.search(sf.text))


@dataclass
class Context:
    root: str
    config: "Config"
    _files: list[SourceFile] | None = None
    _platforms: set[str] | None = None

    # -- Dateien ------------------------------------------------------------
    def all_files(self) -> list[SourceFile]:
        if self._files is not None:
            return self._files
        found: list[SourceFile] = []
        exclude_dirs = DEFAULT_EXCLUDE_DIRS | set(self.config.exclude_dirs)
        root_real = os.path.realpath(self.root)

        def walk_error(exc: OSError) -> None:
            raise GateInputError(
                f"Eingabeverzeichnis nicht lesbar: {exc.filename or self.root}: {exc}"
            ) from exc

        for dirpath, dirnames, filenames in os.walk(self.root, onerror=walk_error):
            dirnames[:] = [
                d for d in dirnames
                if d not in exclude_dirs and not d.endswith(".xcassets")
            ]
            for name in filenames:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, self.root)
                if name in DEFAULT_EXCLUDE_FILES:
                    continue
                if any(fnmatch.fnmatch(rel, pat) for pat in self.config.exclude_globs):
                    continue
                resolved = os.path.realpath(full)
                try:
                    inside = os.path.commonpath((root_real, resolved)) == root_real
                except ValueError:
                    inside = False
                if not inside:
                    raise GateInputError(
                        f"Eingabepfad verlässt die Prüfwurzel: {rel}"
                    )
                try:
                    if os.path.getsize(full) > self.config.max_file_bytes:
                        continue
                    # Nicht erst hoffen, dass irgendein Check die Datei liest:
                    # eine unlesbare Eingabe macht den gesamten Lauf ungültig.
                    with open(full, "rb"):
                        pass
                except OSError as exc:
                    raise GateInputError(
                        f"Eingabedatei nicht prüfbar: {rel}: {exc}"
                    ) from exc
                found.append(SourceFile(
                    path=full, rel=rel, ext=os.path.splitext(name)[1].lower()
                ))
        self._files = found
        return found

    def files(self, *exts: str) -> list[SourceFile]:
        """Quelldateien der genannten Endungen, OHNE Regel-/Testdefinitionen.

        Wer die Gate-Dateien selbst mitprüft, lässt die Dokumentation eines
        Fehlers denselben Alarm auslösen wie den Fehler.
        """
        wanted = {e.lower() for e in exts}
        return [f for f in self.all_files()
                if f.ext in wanted and not is_rule_definition_file(f)]

    def files_including_rules(self, *exts: str) -> list[SourceFile]:
        """Wie files(), aber inklusive Regel-/Testdefinitionen — für Checks,
        die gerade die Gate-Infrastruktur prüfen."""
        wanted = {e.lower() for e in exts}
        return [f for f in self.all_files() if f.ext in wanted]

    def files_named(self, *names: str) -> list[SourceFile]:
        wanted = {n.lower() for n in names}
        return [f for f in self.all_files() if os.path.basename(f.rel).lower() in wanted]

    def dirs_with_suffix(self, suffix: str) -> list[str]:
        out = []

        def walk_error(exc: OSError) -> None:
            raise GateInputError(
                f"Eingabeverzeichnis nicht lesbar: {exc.filename or self.root}: {exc}"
            ) from exc

        exclude_dirs = DEFAULT_EXCLUDE_DIRS | set(self.config.exclude_dirs)
        for dirpath, dirnames, _ in os.walk(self.root, onerror=walk_error):
            dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
            for d in dirnames:
                if d.endswith(suffix):
                    out.append(os.path.join(dirpath, d))
        return out

    # -- Plattform-Erkennung ------------------------------------------------
    def platforms(self) -> set[str]:
        """Erkennt Plattformen an EIGENSCHAFTEN des Projekts, nicht an Namen."""
        if self._platforms is not None:
            return self._platforms
        p: set[str] = {"universal"}
        exts = {f.ext for f in self.all_files()}
        names = {os.path.basename(f.rel).lower() for f in self.all_files()}

        if ".swift" in exts or self.dirs_with_suffix(".xcodeproj"):
            p.add("apple")
        if {".ts", ".tsx", ".jsx"} & exts or "package.json" in names:
            p.add("web")
        if ".gd" in exts or "project.godot" in names:
            p.add("godot")
        if ".cs" in exts or ".csproj" in exts or ".xaml" in exts:
            p.add("dotnet")
        # Unreal: erkannt an .uproject/.uplugin, an Build.cs/Target.cs oder an
        # den UE-Reflection-Makros — nie am Ordnernamen. Ein C++-Projekt ohne
        # UCLASS/GENERATED_BODY ist kein Unreal-Projekt.
        # Diese Erkennung MUSS zu _is_unreal() in checks/unreal.py passen,
        # sonst laufen die Unreal-Checks stillschweigend gar nicht (belegter
        # Fehler: 'serial' fehlte in der Raspberry-Erkennung, ein echter
        # Verstoss meldete gruen).
        if (".uproject" in exts or ".uplugin" in exts
                or any(f.rel.endswith(("Build.cs", "Target.cs"))
                       for f in self.all_files())):
            p.add("unreal")
        elif {".cpp", ".h"} & exts:
            _ue_macro = re.compile(
                r"\b(?:UCLASS|USTRUCT|UENUM|GENERATED_BODY|UPROPERTY)\s*\("
            )
            for f in self.files(".cpp", ".h"):
                if _ue_macro.search(f.text):
                    p.add("unreal")
                    break
        if ".py" in exts:
            p.add("python")
        # Raspberry: erkannt an Hardware-Bibliotheken, nicht am Verzeichnisnamen
        if "python" in p:
            # Diese Liste MUSS zu HW_IMPORT in checks/raspberry.py passen —
            # sonst erkennt die Plattform ein Projekt nicht, dessen Checks
            # dann stillschweigend gar nicht laufen. Belegt in der Gegenprobe:
            # 'import serial' wurde vom Check erkannt, von der Plattform nicht,
            # und ein echter Verstoß meldete grün.
            hw = re.compile(
                r"^\s*(?:import|from)\s+(RPi\.GPIO|RPi|gpiozero|smbus2?|spidev|"
                r"pigpio|serial|w1thermsensor|board|busio|adafruit_\w+|"
                r"picamera2?|luma\.\w+)\b",
                re.MULTILINE,
            )
            for f in self.files(".py"):
                if hw.search(f.text):
                    p.add("raspberry")
                    break
        self._platforms = p
        return p

    # -- Git ----------------------------------------------------------------
    def changed_files(self, base: str) -> list[str]:
        """Geänderte Dateien gegen eine Basis, relativ zu ``root``.

        Git gibt Namen standardmäßig relativ zur Repository-Wurzel aus. Für
        einen geprüften Unterordner würde das Befunde still wegfiltern. Darum
        wird der Pfadbereich ausdrücklich begrenzt und jeder Rückgabepfad auf
        Ausbruch aus der Prüfwurzel geprüft.
        """
        if not base or base.startswith("-") or "\0" in base:
            raise ChangedFilesError("Ungültige Git-Referenz für --changed-only.")
        try:
            top = subprocess.run(
                ["git", "-C", self.root, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ChangedFilesError(f"Git-Aufruf fehlgeschlagen: {exc}") from exc
        if top.returncode != 0:
            detail = top.stderr.strip() or "kein Git-Repository"
            raise ChangedFilesError(detail)

        repo_root = os.path.realpath(top.stdout.strip())
        root = os.path.realpath(self.root)
        try:
            if os.path.commonpath((repo_root, root)) != repo_root:
                raise ChangedFilesError("Prüfwurzel liegt außerhalb des Git-Repositories.")
        except ValueError as exc:
            raise ChangedFilesError("Prüfwurzel und Git-Repository sind inkompatibel.") from exc

        root_rel = os.path.relpath(root, repo_root)
        pathspec = "." if root_rel == "." else root_rel.replace(os.sep, "/")
        try:
            diff = subprocess.run(
                ["git", "-C", repo_root, "diff", "--name-only", "-z", base,
                 "--", pathspec],
                capture_output=True, timeout=30,
            )
            untracked = subprocess.run(
                ["git", "-C", repo_root, "ls-files", "--others",
                 "--exclude-standard", "-z", "--", pathspec],
                capture_output=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ChangedFilesError(f"Git-Diff fehlgeschlagen: {exc}") from exc
        if diff.returncode != 0:
            detail = os.fsdecode(diff.stderr).strip() or "ungültige Git-Referenz"
            raise ChangedFilesError(detail)
        if untracked.returncode != 0:
            detail = os.fsdecode(untracked.stderr).strip() or "ungetrackte Dateien nicht ermittelbar"
            raise ChangedFilesError(detail)

        changed: set[str] = set()
        for raw in (diff.stdout + untracked.stdout).split(b"\0"):
            if not raw:
                continue
            name = os.fsdecode(raw)
            if os.path.isabs(name):
                raise ChangedFilesError(f"Git lieferte absoluten Pfad: {name}")
            candidate = os.path.abspath(os.path.join(repo_root, name))
            try:
                inside = os.path.commonpath((root, candidate)) == root
            except ValueError:
                inside = False
            if not inside:
                raise ChangedFilesError(
                    f"Git-Pfad verlässt die Prüfwurzel: {name}"
                )
            changed.add(os.path.relpath(candidate, root).replace(os.sep, "/"))
        return sorted(changed)


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

@dataclass
class Config:
    # check_id (oder Präfix mit '*') -> "error" | "warning" | "off"
    severity_overrides: dict[str, str] = field(default_factory=dict)
    exclude_dirs: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)
    brand_names: list[str] = field(default_factory=list)
    brand_source_globs: list[str] = field(default_factory=list)
    max_file_bytes: int = 2_000_000
    # Ohne Profil laufen nur die universell sicheren Checks hart.
    strict: bool = False
    profile_path: str | None = None

    def severity_for(self, check_id: str, default: Severity) -> Severity | None:
        """None = Check ist abgeschaltet."""
        best: str | None = None
        best_len = -1
        for pattern, value in self.severity_overrides.items():
            if pattern == check_id or (
                pattern.endswith("*") and check_id.startswith(pattern[:-1])
            ):
                if len(pattern) > best_len:
                    best, best_len = value, len(pattern)
        if best is None:
            return default
        if best == "off":
            return None
        return Severity(best)

    @classmethod
    def load(cls, root: str, explicit: str | None = None) -> "Config":
        path = explicit or os.path.join(root, ".qualitygate.toml")
        if not os.path.isfile(path):
            if explicit is not None:
                raise ConfigError(f"Konfigurationsdatei fehlt: {path}")
            return cls()
        try:
            import tomllib
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"Konfiguration nicht lesbar: {path}: {exc}") from exc

        allowed_tables = {"gate", "project", "brand", "severity"}
        unknown_tables = sorted(set(data) - allowed_tables)
        if unknown_tables:
            raise ConfigError(
                "Unbekannte Konfigurationstabellen: " + ", ".join(unknown_tables)
            )

        def table(name: str, allowed_keys: set[str] | None = None) -> dict:
            value = data.get(name, {})
            if not isinstance(value, dict):
                raise ConfigError(f"[{name}] muss eine TOML-Tabelle sein.")
            if allowed_keys is not None:
                unknown = sorted(set(value) - allowed_keys)
                if unknown:
                    raise ConfigError(
                        f"[{name}] enthält unbekannte Schlüssel: " + ", ".join(unknown)
                    )
            return value

        def string_list(owner: str, key: str, value: object) -> list[str]:
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item for item in value
            ):
                raise ConfigError(
                    f"{owner}.{key} muss eine Liste nichtleerer Strings sein."
                )
            return value

        cfg = cls(profile_path=os.path.abspath(path))
        gate = table("gate", {"strict", "exclude_dirs", "exclude", "max_file_bytes"})
        strict = gate.get("strict", False)
        if not isinstance(strict, bool):
            raise ConfigError("gate.strict muss true oder false sein.")
        cfg.strict = strict
        cfg.exclude_dirs = string_list(
            "gate", "exclude_dirs", gate.get("exclude_dirs", [])
        )
        cfg.exclude_globs = string_list(
            "gate", "exclude", gate.get("exclude", [])
        )
        max_bytes = gate.get("max_file_bytes", cfg.max_file_bytes)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ConfigError("gate.max_file_bytes muss eine positive Ganzzahl sein.")
        cfg.max_file_bytes = max_bytes

        project = table("project", {"name", "platform"})
        project_name = project.get("name")
        project_platform = project.get("platform")
        if project_name is not None and (not isinstance(project_name, str) or not project_name):
            raise ConfigError("project.name muss ein nichtleerer String sein.")
        if project_platform is not None and project_platform not in {
            "universal", "apple", "web", "godot", "dotnet", "python",
            "raspberry", "unreal",
        }:
            raise ConfigError("project.platform ist unbekannt.")

        brand = table("brand", {"name", "names", "source", "sources"})
        cfg.brand_names = string_list("brand", "names", brand.get("names", []))
        singular_name = brand.get("name")
        if singular_name is not None:
            if not isinstance(singular_name, str) or not singular_name:
                raise ConfigError("brand.name muss ein nichtleerer String sein.")
            cfg.brand_names.append(singular_name)
        if not cfg.brand_names and project_name:
            cfg.brand_names.append(project_name)
        cfg.brand_names = list(dict.fromkeys(cfg.brand_names))

        cfg.brand_source_globs = string_list(
            "brand", "sources", brand.get("sources", [])
        )
        singular_source = brand.get("source")
        if singular_source is not None:
            if not isinstance(singular_source, str) or not singular_source:
                raise ConfigError("brand.source muss ein nichtleerer String sein.")
            source_path = singular_source.rsplit(":", 1)[0]
            if not source_path:
                raise ConfigError("brand.source muss einen Dateipfad enthalten.")
            cfg.brand_source_globs.append(source_path)
        cfg.brand_source_globs = list(dict.fromkeys(cfg.brand_source_globs))

        severity = table("severity")
        allowed = {member.value for member in Severity} | {"off"}
        for key, value in severity.items():
            if not isinstance(key, str) or not key:
                raise ConfigError("severity-Schlüssel müssen nichtleere Strings sein.")
            if not isinstance(value, str) or value not in allowed:
                choices = ", ".join(sorted(allowed))
                raise ConfigError(
                    f"severity.{key} muss einer von {choices} sein."
                )
            cfg.severity_overrides[key] = value
        return cfg


# ---------------------------------------------------------------------------
# Check-Registry
# ---------------------------------------------------------------------------

@dataclass
class Check:
    id: str
    title: str
    platform: str
    default_severity: Severity
    fn: Callable[[Context], CheckResult]
    guideline: str = ""
    self_tests: list[SelfTestCase] = field(default_factory=list)
    # True = dieser Check ist auch ohne Profil hart. Nur für Prüfungen, die in
    # einem fremden Projekt nicht falsch-positiv werden können.
    safe_by_default: bool = False


REGISTRY: dict[str, Check] = {}


def register(
    check_id: str,
    title: str,
    platform: str = "universal",
    severity: Severity = Severity.WARNING,
    guideline: str = "",
    self_tests: Sequence[SelfTestCase] = (),
    safe_by_default: bool = False,
):
    def deco(fn: Callable[[Context], CheckResult]):
        if check_id in REGISTRY:
            raise RuntimeError(f"Doppelte Check-ID: {check_id}")
        REGISTRY[check_id] = Check(
            id=check_id, title=title, platform=platform,
            default_severity=severity, fn=fn, guideline=guideline,
            self_tests=list(self_tests), safe_by_default=safe_by_default,
        )
        return fn
    return deco


# ---------------------------------------------------------------------------
# Hilfsfunktionen für Checks
# ---------------------------------------------------------------------------

def ok(check_id: str, title: str, units: int, label: str = "Dateien",
       platform: str = "universal") -> CheckResult:
    """Bestanden — aber null geprüfte Einheiten sind NICHT bestanden.

    "0 von 0 Dateien sauber" ist trivial wahr und sagt nichts. Jede Suche nach
    einem Muster braucht davor die Prüfung, dass überhaupt etwas zu
    durchsuchen war; sonst ist die stärkste Aussage des Gates die, die am
    leichtesten falsch grün wird.
    """
    if units <= 0:
        return CheckResult(
            check_id, Status.UNMEASURED, title,
            reason=f"Null {label} geprüft — es gab nichts zu messen.",
            units_examined=0, unit_label=label, platform=platform,
        )
    return CheckResult(check_id, Status.PASS, title, units_examined=units,
                       unit_label=label, platform=platform)


def unmeasured(check_id: str, title: str, reason: str,
               platform: str = "universal") -> CheckResult:
    return CheckResult(check_id, Status.UNMEASURED, title, reason=reason,
                       platform=platform)


def failed(check_id: str, title: str, findings: list[Finding], units: int,
           label: str = "Dateien", platform: str = "universal") -> CheckResult:
    return CheckResult(check_id, Status.FAIL, title, findings=findings,
                       units_examined=units, unit_label=label, platform=platform)


def result_for(check_id: str, title: str, findings: list[Finding], units: int,
               label: str = "Dateien", platform: str = "universal") -> CheckResult:
    if findings:
        return failed(check_id, title, findings, units, label, platform)
    return ok(check_id, title, units, label, platform)


def iter_matches(sf: SourceFile, pattern: re.Pattern, *,
                 skip_comments: bool = True) -> Iterator[tuple[int, re.Match, str]]:
    """Liefert (Zeilennummer, Match, Zeilentext) — Kommentare optional entfernt."""
    haystack = strip_comments(sf.text, sf.ext) if skip_comments else sf.text
    for m in pattern.finditer(haystack):
        line_no = haystack.count("\n", 0, m.start()) + 1
        raw_lines = sf.lines
        raw = raw_lines[line_no - 1] if 0 < line_no <= len(raw_lines) else ""
        yield line_no, m, raw.strip()


def snippet(text: str, limit: int = 120) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 1] + "…"
