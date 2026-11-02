"""
Repository-Inhalt: was veröffentlicht wird, muss zum Produkt gehören.

Interne Arbeitsnotizen (Übergabeprotokolle zwischen Sessions, die private
Master-Roadmap) beschreiben Zwischenstände, lokale Pfade und offene Baustellen.
In einem öffentlichen Repository sind sie kein Code, sondern ein Leck — und
nach dem Push stehen sie in der Historie, auch wenn sie später gelöscht werden.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

from ruttla.discovery import DEFAULT_EXCLUDE_DIRS, to_posix
from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, unmeasured,
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


_GITHUB_REMOTE = re.compile(
    r"github\.com[:/](?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


def _origin_url(root: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", root, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def github_visibility(owner: str, name: str) -> str | None:
    """"public", "private" oder None (nicht messbar).

    Anonymer Lesezugriff: ein öffentliches Repo liefert 200 mit
    ``private: false``, ein privates ist für Anonyme 404. Rate-Limit,
    Netzfehler und alles andere sind ausdrücklich *nicht gemessen*.
    """
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{name}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ruttla"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        return "private" if exc.code == 404 else None
    except (OSError, ValueError):
        return None
    if data.get("private") is False:
        return "public"
    return None


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
        # Ohne Git ist der Baum selbst die Auslieferung (Export, Archiv).
        candidates = _tree_files(ctx)
        scope = "Dateien im Baum (kein Git)"
    else:
        # Im Git-Repo gilt die Regel nur für öffentliche Repos: in einem
        # privaten sind die Notizen gewollt (Übergabe zwischen Rechnern).
        url = _origin_url(ctx.root)
        match = _GITHUB_REMOTE.search(url or "")
        if not match:
            return unmeasured(CHECK_ID, title,
                              "Kein GitHub-Remote 'origin' — Sichtbarkeit unbekannt.")
        if not ctx.config.allow_network:
            return unmeasured(CHECK_ID, title,
                              "Repo-Sichtbarkeit nur mit --allow-network messbar.")
        visibility = github_visibility(match["owner"], match["name"])
        if visibility is None:
            return unmeasured(CHECK_ID, title,
                              "GitHub-Sichtbarkeit nicht abrufbar (Netz/Rate-Limit).")
        if visibility == "private":
            return result_for(CHECK_ID, title, [], 1, "privates Repo (Regel gilt nur öffentlich)")
        scope = "veröffentlichbare Dateien (öffentliches Git-Repo)"

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


BYTECODE_CHECK_ID = "repo.python_bytecode_tracked"
BYTECODE_GUIDELINE = "CLAUDE.md § 'Ein Gate, das aus einem Artefakt liest, prüft den Stand des Artefakts'"


def _tracked_files(root: str) -> list[str] | None:
    """Getrackte Dateien relativ zu ``root``; None ohne lesbares Git."""
    try:
        proc = subprocess.run(
            ["git", "-C", root, "ls-files", "--cached", "-z"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [os.fsdecode(p) for p in proc.stdout.split(b"\0") if p]


def _is_bytecode(rel: str) -> bool:
    return rel.endswith((".pyc", ".pyo")) or "__pycache__" in rel.split("/")


@register(
    BYTECODE_CHECK_ID,
    "Python-Bytecode (__pycache__/*.pyc) unter Versionskontrolle",
    platform="universal",
    severity=Severity.WARNING,
    guideline=BYTECODE_GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Bytecode im Index",
            files={
                "tools/gate.py": "print('ok')\n",
                "tools/__pycache__/gate.cpython-312.pyc": "bytecode\n",
                ".ruttla-selftest/git-index.json": json.dumps({"modes": {
                    "tools/gate.py": "100644",
                    "tools/__pycache__/gate.cpython-312.pyc": "100644"}}),
            },
            expect=Status.FAIL,
            expect_finding_contains="gate.cpython-312.pyc",
            expect_findings=1,
        ),
        SelfTestCase(
            name="Bytecode nur lokal, ignoriert",
            files={
                "tools/gate.py": "print('ok')\n",
                ".gitignore": "__pycache__/\n",
                "tools/__pycache__/gate.cpython-312.pyc": "bytecode\n",
                ".ruttla-selftest/git-index.json": json.dumps({"modes": {
                    "tools/gate.py": "100644", ".gitignore": "100644"}}),
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Kein Git-Repo",
            files={"tools/gate.py": "print('ok')\n"},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_python_bytecode_tracked(ctx: Context) -> CheckResult:
    """Findet getrackten Python-Bytecode.

    Python schreibt ``__pycache__/*.pyc`` bei jedem Lauf neu, sobald die
    Quelle neuer ist. Getrackt ist er damit eine Eingabe, die sich während
    eines Sammellaufs ändert: Belegt am 02.11.2026 (WiesnSurvivors) meldete
    Ruttla nach einem vollständig grünen Lauf sechs Laufzeitnachweise als
    veraltet, weil ein späterer Schritt 14 getrackte .pyc neu geschrieben
    hatte. Dazu kommt Rauschen in jedem Diff.
    """
    title = "Python-Bytecode (__pycache__/*.pyc) unter Versionskontrolle"
    tracked = _tracked_files(ctx.root)
    if tracked is None:
        return unmeasured(BYTECODE_CHECK_ID, title, "Kein Git-Repository — Versionskontrolle nicht messbar.")
    if not tracked:
        return unmeasured(BYTECODE_CHECK_ID, title, "Keine getrackten Dateien.")
    findings = [Finding(
        check_id=BYTECODE_CHECK_ID,
        severity=Severity.WARNING,
        message=f"{rel} ist Python-Bytecode und wird mitversioniert.",
        file=rel,
        line=1,
        evidence=os.path.basename(rel),
        fix=("`__pycache__/` und `*.pyc` in .gitignore eintragen und "
             f"`git rm --cached {rel}` — die Datei bleibt lokal erhalten."),
        guideline=BYTECODE_GUIDELINE,
    ) for rel in sorted(tracked) if _is_bytecode(rel)]
    return result_for(BYTECODE_CHECK_ID, title, findings, len(tracked), "getrackte Dateien")
