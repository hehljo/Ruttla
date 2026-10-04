"""Scan context handed to every check: file access, platforms, git."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field, replace

from . import git as _git
from .config import Config
from .discovery import (
    DEFAULT_EXCLUDE_DIRS,
    Coverage,
    SourceFile,
    inventory,
    is_rule_definition_file,
    to_posix,
)
from .models import GateInputError
from .platforms import ProjectRoot, claimed_files, detect_platforms, find_roots


@dataclass
class Context:
    root: str
    config: Config
    _files: list[SourceFile] | None = None
    _coverage: Coverage | None = None
    # Sicht einer Plattform (P10-T003): Dateien, die innerhalb einer fremden
    # Projektwurzel einer anderen Plattform gehören, sind darin unsichtbar.
    scope: str | None = None
    _scoped_files: list[SourceFile] | None = None
    # Zwischen Gesamt- und Plattformsichten geteilt: Plattformen, Wurzeln,
    # Ansprüche und die Sichten selbst werden je Lauf nur einmal berechnet.
    _shared: dict = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        self._shared.setdefault("base", self)

    # -- Dateien ------------------------------------------------------------
    def _inventory(self) -> list[SourceFile]:
        if self._files is None:
            self._files, self._coverage = inventory(self.root, self.config)
        return self._files

    def all_files(self) -> list[SourceFile]:
        files = self._inventory()
        if self.scope is None:
            return files
        if self._scoped_files is None:
            owners = self.claims()
            self._scoped_files = [
                f for f in files if owners.get(f.rel, self.scope) == self.scope
            ]
        return self._scoped_files

    def scoped(self, platform: str) -> "Context":
        """Sicht der Plattform ``platform``; universal sieht alles."""
        if platform == "universal":
            return self if self.scope is None else self.unscoped()
        views = self._shared.setdefault("views", {})
        if platform not in views:
            self._inventory()
            views[platform] = replace(self, scope=platform, _scoped_files=None)
        return views[platform]

    def unscoped(self) -> "Context":
        return self._shared.get("base", self)

    def project_roots(self) -> list[ProjectRoot]:
        if "roots" not in self._shared:
            self._shared["roots"] = find_roots(self._inventory())
        return self._shared["roots"]

    def claims(self) -> dict[str, str]:
        if "claims" not in self._shared:
            self._shared["claims"] = claimed_files(self._inventory(), self.project_roots())
        return self._shared["claims"]

    def coverage(self) -> Coverage:
        self._inventory()
        assert self._coverage is not None
        return self._coverage

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
            # Profile globs apply here too: an excluded .xcodeproj/.uproject
            # must neither switch a platform on nor be measured (found by the
            # dogfood scan, 2026-09-24 — excluded fixtures were reported).
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in exclude_dirs
                and not self._excluded_dir(os.path.join(dirpath, d))
            )
            for d in dirnames:
                if d.endswith(suffix):
                    out.append(os.path.join(dirpath, d))
        return out

    def _excluded_dir(self, path: str) -> bool:
        rel = to_posix(os.path.relpath(path, self.root))
        return any(
            fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel + "/", pat)
            for pat in self.config.exclude_globs
        )

    # -- Plattformen --------------------------------------------------------
    def detected_platforms(self) -> set[str]:
        return detect_platforms(self.unscoped())

    def platforms(self) -> set[str]:
        """Detected platforms plus the profile's ``project.platform`` (additive)."""
        if "platforms" not in self._shared:
            platforms = self.unscoped().detected_platforms()
            if self.config.project_platform:
                platforms.add(self.config.project_platform)
            self._shared["platforms"] = platforms
        return self._shared["platforms"]

    # -- Git ----------------------------------------------------------------
    def changed_files(self, base: str) -> list[str]:
        return _git.changed_files(self.root, base)
