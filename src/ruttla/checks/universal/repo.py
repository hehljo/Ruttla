"""
Repository-Inhalt: was veröffentlicht wird, muss zum Produkt gehören.

Interne Arbeitsnotizen (Übergabeprotokolle zwischen Sessions, die private
Master-Roadmap) beschreiben Zwischenstände, lokale Pfade und offene Baustellen.
In einem öffentlichen Repository sind sie kein Code, sondern ein Leck — und
nach dem Push stehen sie in der Historie, auch wenn sie später gelöscht werden.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess

from ruttla.discovery import DEFAULT_EXCLUDE_DIRS, to_posix
from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for,
)

CHECK_ID = "repo.internal_notes_published"
GUIDELINE = "GUIDELINES.md § Internal notes stay local"

# Dateinamen, die der Agenten-Workflow selbst als interne Notizen anlegt
# (globale Regel: „MASTER_ROADMAP.md und HANDOVER.md pflegen"). Der Name ist
# hier die Eigenschaft: er wird vom Workflow erzeugt, nicht vom Produkt.
INTERNAL_NOTE_PATTERNS = ("handover*.md", "master_roadmap*.md")


def _published_candidates(root: str) -> list[str] | None:
    """Dateien, die ein Push veröffentlichen würde, relativ zu ``root``.

    Im Git-Repository: getrackt ODER neu und nicht ignoriert — sonst wäre die
    Datei, die gerade erst angelegt wurde, unsichtbar. Ohne Git: None, dann
    gilt der ganze Baum als Auslieferung.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", root, "ls-files", "--cached", "--others",
             "--exclude-standard", "-z"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [os.fsdecode(p) for p in proc.stdout.split(b"\0") if p]


def _tree_files(ctx: Context) -> list[str]:
    """Ohne Git: der ganze Baum. Bewusst NICHT ctx.all_files() — das Inventar
    blendet genau diese Notizen als Agenten-Dateien aus."""
    exclude = DEFAULT_EXCLUDE_DIRS | set(ctx.config.exclude_dirs)
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ctx.root):
        dirnames[:] = sorted(d for d in dirnames if d not in exclude)
        out.extend(to_posix(os.path.relpath(os.path.join(dirpath, n), ctx.root))
                   for n in filenames)
    return out


def _is_internal_note(rel: str) -> bool:
    name = os.path.basename(rel).lower()
    return any(fnmatch.fnmatch(name, pat) for pat in INTERNAL_NOTE_PATTERNS)


@register(
    CHECK_ID,
    "Interne Arbeitsnotizen (Handover/Master-Roadmap) im veröffentlichten Repo",
    platform="universal",
    severity=Severity.ERROR,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Handover und Master-Roadmap liegen im Baum",
            files={
                "README.md": "# App\n",
                "HANDOVER.md": "# Übergabe\n",
                "docs/MASTER_ROADMAP.md": "# Roadmap\n",
            },
            expect=Status.FAIL,
            expect_finding_contains="HANDOVER.md",
        ),
        SelfTestCase(
            name="Nur Produktdoku",
            files={
                "README.md": "# App\n",
                "CHANGELOG.md": "# Changelog\n",
                "docs/ROADMAP-public.md": "# Öffentliche Roadmap\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_internal_notes_published(ctx: Context) -> CheckResult:
    """Findet Übergabeprotokolle und die interne Master-Roadmap in Dateien,
    die ein Push veröffentlichen würde.

    Belegt am 30.09.2026: eine App war live im Mac App Store, ihr
    öffentliches Repo trug HANDOVER.md und MASTER_ROADMAP.md mit internen
    Zwischenständen. Lokal bleiben sie — nur eben per .gitignore.
    """
    title = "Interne Arbeitsnotizen (Handover/Master-Roadmap) im veröffentlichten Repo"
    candidates = _published_candidates(ctx.root)
    if candidates is None:
        candidates = _tree_files(ctx)
        scope = "Dateien im Baum (kein Git)"
    else:
        scope = "veröffentlichbare Dateien (Git)"

    findings: list[Finding] = []
    for rel in sorted(candidates):
        if not _is_internal_note(rel):
            continue
        findings.append(Finding(
            check_id=CHECK_ID,
            severity=Severity.ERROR,
            message=f"{rel} ist eine interne Arbeitsnotiz und würde veröffentlicht.",
            file=rel,
            line=1,
            evidence=os.path.basename(rel),
            fix=(f"`git rm --cached {rel}` und den Namen in .gitignore eintragen — "
                 "die Datei bleibt lokal erhalten. Bereits gepushte Stände "
                 "bleiben in der Historie."),
            guideline=GUIDELINE,
        ))

    return result_for(CHECK_ID, title, findings, len(candidates), scope)
