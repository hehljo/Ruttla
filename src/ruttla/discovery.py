"""Safe file inventory, comment stripping and self-description detection.

The scan target is untrusted data (docs/SECURITY_DESIGN.md): files are read,
never imported or executed; symlinks may not leave the scan root; an
unreadable input invalidates the whole run instead of being skipped.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .models import GateInputError

if TYPE_CHECKING:  # pragma: no cover
    from .config import Config

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

# Agent instruction files and gate profiles DESCRIBE rules by their role;
# otherwise documenting a failure raises the same alarm as the failure.
# README.md and CHANGELOG.md are deliberately NOT in this set any more
# (P02-T007): they are the target project's public documentation and the
# docs checks must be able to measure them. A Markdown file that documents
# rules marks itself with RULE_DOCS_MARKER instead (property, not basename).
AGENT_INSTRUCTION_FILES = {
    "CLAUDE.md", "AGENTS.md", "GEMINI.md", "HANDOVER.md",
    "ROADMAP.md", "MASTER_ROADMAP.md", ".qualitygate.toml", ".ruttla.toml",
}
# Legacy name kept for check modules and callers of the 0.x API.
DEFAULT_EXCLUDE_FILES = AGENT_INSTRUCTION_FILES

RULE_DOCS_MARKER = "<!-- ruttla:rule-docs -->"


def to_posix(rel: str) -> str:
    """Report paths always use '/' — on every OS (SARIF, --changed-only)."""
    return rel.replace(os.sep, "/") if os.sep != "/" else rel


@dataclass
class SourceFile:
    path: str          # absolut
    rel: str           # relativ zur Projektwurzel, immer mit '/'
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


@dataclass
class SkippedFile:
    rel: str
    reason: str        # "max_file_bytes"
    size: int

    def to_dict(self) -> dict:
        return {"file": self.rel, "reason": self.reason, "bytes": self.size}


@dataclass
class Coverage:
    """What the inventory did NOT hand to the checks, and why (FR-013)."""

    files_scanned: int = 0
    skipped: list[SkippedFile] = field(default_factory=list)
    excluded_agent_files: int = 0
    excluded_by_config: int = 0
    max_file_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "files_scanned": self.files_scanned,
            "files_skipped": [s.to_dict() for s in self.skipped],
            "files_skipped_total": len(self.skipped),
            "files_excluded_agent_instructions": self.excluded_agent_files,
            "files_excluded_by_config": self.excluded_by_config,
            "max_file_bytes": self.max_file_bytes,
        }


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


# Eine Datei, die Prüfmuster oder Sabotage-Testdaten ENTHÄLT, verletzt die
# Regeln nicht — sie beschreibt sie. Ohne diese Ausnahme meldet das Gate seine
# eigenen Testfälle als Befunde, und jedes Projekt, das eigene Gates mitführt,
# bekommt dieselben falschen Treffer. Gemessen wird die Eigenschaft "diese
# Datei definiert Prüfungen", nicht ein Pfadname.
_SELF_DESCRIBING = re.compile(
    r"(?:^|\n)\s*(?:@register\s*\(|SelfTestCase\s*\(|def\s+test_\w+|"
    r"class\s+Test\w+|describe\s*\(|it\s*\(\s*[\"'])"
    r"|" + re.escape(RULE_DOCS_MARKER)
)


def is_rule_definition_file(sf: SourceFile) -> bool:
    """True für Dateien, die Prüfregeln oder Testfälle definieren/dokumentieren."""
    return bool(_SELF_DESCRIBING.search(sf.text))


def inventory(root: str, config: "Config") -> tuple[list[SourceFile], Coverage]:
    """Walk ``root`` once; every file is either handed on or accounted for."""
    found: list[SourceFile] = []
    coverage = Coverage(max_file_bytes=config.max_file_bytes)
    exclude_dirs = DEFAULT_EXCLUDE_DIRS | set(config.exclude_dirs)
    root_real = os.path.realpath(root)

    def walk_error(exc: OSError) -> None:
        raise GateInputError(
            f"Eingabeverzeichnis nicht lesbar: {exc.filename or root}: {exc}"
        ) from exc

    for dirpath, dirnames, filenames in os.walk(root, onerror=walk_error):
        # Deterministic order on every OS and file system (FR-012).
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in exclude_dirs and not d.endswith(".xcassets")
        )
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = to_posix(os.path.relpath(full, root))
            if name in AGENT_INSTRUCTION_FILES:
                coverage.excluded_agent_files += 1
                continue
            if any(fnmatch.fnmatch(rel, pat) for pat in config.exclude_globs):
                coverage.excluded_by_config += 1
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
                size = os.path.getsize(full)
                if size > config.max_file_bytes:
                    # Not silent any more (P02-T008): reported as coverage
                    # diagnostic in every output format.
                    coverage.skipped.append(SkippedFile(rel, "max_file_bytes", size))
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
    coverage.files_scanned = len(found)
    return found, coverage
