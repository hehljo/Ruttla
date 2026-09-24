"""Scan context handed to every check: file access, platforms, git."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass

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
from .platforms import detect_platforms


@dataclass
class Context:
    root: str
    config: Config
    _files: list[SourceFile] | None = None
    _platforms: set[str] | None = None
    _coverage: Coverage | None = None

    # -- Dateien ------------------------------------------------------------
    def all_files(self) -> list[SourceFile]:
        if self._files is None:
            self._files, self._coverage = inventory(self.root, self.config)
        return self._files

    def coverage(self) -> Coverage:
        self.all_files()
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
        return detect_platforms(self)

    def platforms(self) -> set[str]:
        """Detected platforms plus the profile's ``project.platform`` (additive)."""
        if self._platforms is None:
            platforms = self.detected_platforms()
            if self.config.project_platform:
                platforms.add(self.config.project_platform)
            self._platforms = platforms
        return self._platforms

    # -- Git ----------------------------------------------------------------
    def changed_files(self, base: str) -> list[str]:
        return _git.changed_files(self.root, base)
