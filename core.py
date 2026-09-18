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
            except OSError:
                self._text = ""
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
    ".rs": "//", ".gd": "#", ".py": "#", ".sh": "#", ".rb": "#", ".yaml": "#",
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
        for dirpath, dirnames, filenames in os.walk(self.root):
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
                try:
                    if os.path.getsize(full) > self.config.max_file_bytes:
                        continue
                except OSError:
                    continue
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
        for dirpath, dirnames, _ in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS]
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
    def changed_files(self, base: str) -> list[str] | None:
        """Geänderte Dateien gegen eine Basis. None = nicht ermittelbar."""
        try:
            res = subprocess.run(
                ["git", "-C", self.root, "diff", "--name-only", base],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if res.returncode != 0:
            return None
        return [ln for ln in res.stdout.splitlines() if ln.strip()]


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
            return cls()
        try:
            import tomllib
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except Exception:
            return cls()

        cfg = cls(profile_path=path)
        gate = data.get("gate", {})
        cfg.strict = bool(gate.get("strict", False))
        cfg.exclude_dirs = list(gate.get("exclude_dirs", []))
        cfg.exclude_globs = list(gate.get("exclude", []))
        cfg.max_file_bytes = int(gate.get("max_file_bytes", cfg.max_file_bytes))

        brand = data.get("brand", {})
        cfg.brand_names = list(brand.get("names", []))
        cfg.brand_source_globs = list(brand.get("sources", []))

        for key, value in data.get("severity", {}).items():
            cfg.severity_overrides[key] = str(value)
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
