"""Git-based changed-files selection for ``--changed-only`` (FR-005).

Git is called with argument lists only (never a shell string); every path it
returns is re-checked against the scan root.
"""

from __future__ import annotations

import os
import subprocess

from .models import ChangedFilesError


def changed_files(scan_root: str, base: str) -> list[str]:
    """Geänderte Dateien gegen eine Basis, relativ zu ``scan_root``.

    Git gibt Namen standardmäßig relativ zur Repository-Wurzel aus. Für
    einen geprüften Unterordner würde das Befunde still wegfiltern. Darum
    wird der Pfadbereich ausdrücklich begrenzt und jeder Rückgabepfad auf
    Ausbruch aus der Prüfwurzel geprüft.
    """
    if not base or base.startswith("-") or "\0" in base:
        raise ChangedFilesError("Ungültige Git-Referenz für --changed-only.")
    try:
        top = subprocess.run(
            ["git", "-C", scan_root, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ChangedFilesError(f"Git-Aufruf fehlgeschlagen: {exc}") from exc
    if top.returncode != 0:
        detail = top.stderr.strip() or "kein Git-Repository"
        raise ChangedFilesError(detail)

    repo_root = os.path.realpath(top.stdout.strip())
    root = os.path.realpath(scan_root)
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
