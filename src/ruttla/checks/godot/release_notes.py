"""„Was ist neu“ je Version für Store-Godot-Projekte.

Python statt TOML-Regel: Zustand über mehrere Dateien (Version aus project.godot gegen den Katalog
data/whats_new.json und die Exportpresets), kein Zeilenmuster.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

from ruttla.core import (
    Context,
    CheckResult,
    Finding,
    Severity,
    Status,
    SelfTestCase,
    register,
    unmeasured,
    result_for,
    snippet,
)

PLATFORM = "godot"
_ID = "godot.whats_new_missing_for_version"
_GUIDELINE = "CODE_QUALITY_GUIDELINES_GAMEDEV.md § Was ist neu nach Update"
_VERSION = re.compile(r'^config/version="([^"]*)"', re.M)
_STORE = re.compile(r'^platform="(?:iOS|Android)"', re.M)

_PROJECT = '[application]\nconfig/version="1.2.0"\n'
_IOS = '[preset.0]\nname="iOS"\nplatform="iOS"\n'


def _catalog(version: str, items: list[str]) -> str:
    return json.dumps({"version": 1, "releases": [{"version": version, "items": items}]})


@register(
    _ID,
    "Store-Version ohne „Was ist neu“-Einträge (Fenster nach Update und Store-Text fehlen)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=_GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Version hochgezählt, Katalog nicht nachgezogen",
            files={"project.godot": _PROJECT, "export_presets.cfg": _IOS,
                   "data/whats_new.json": _catalog("1.1.0", ["UI_WHATS_NEW_110_A"])},
            expect=Status.FAIL,
            expect_finding_contains="1.2.0",
        ),
        SelfTestCase(
            name="Eintrag ohne Punkte",
            files={"project.godot": _PROJECT, "export_presets.cfg": _IOS,
                   "data/whats_new.json": _catalog("1.2.0", [])},
            expect=Status.FAIL,
            expect_finding_contains="1.2.0",
        ),
        SelfTestCase(
            name="Store-Projekt ohne Katalog",
            files={"project.godot": _PROJECT, "export_presets.cfg": _IOS},
            expect=Status.FAIL,
            expect_finding_contains="whats_new.json",
        ),
        SelfTestCase(
            name="Katalog passt zur Version",
            files={"project.godot": _PROJECT, "export_presets.cfg": _IOS,
                   "data/whats_new.json": _catalog("1.2.0", ["UI_WHATS_NEW_120_A"])},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Nur Desktop-Export: nicht gemessen",
            files={"project.godot": _PROJECT,
                   "export_presets.cfg": '[preset.0]\nname="Linux"\nplatform="Linux"\n'},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_whats_new_missing_for_version(ctx: Context) -> CheckResult:
    """Jede Store-Version braucht Punkte im Katalog data/whats_new.json: daraus kommen das Fenster
    nach einem Update (einmal je Version) und der „Neuigkeiten“-Text im Store. Ohne Eintrag sieht der
    Spieler nach dem Update nichts, und der Store-Text muss von Hand nachgebaut werden."""
    title = "Store-Version ohne „Was ist neu“-Einträge"
    catalogs = ctx.files_named("whats_new.json")
    presets = ctx.files_named("export_presets.cfg")
    findings: list[Finding] = []
    measured = 0
    for pf in ctx.files_named("project.godot"):
        root = str(PurePosixPath(pf.rel).parent)

        def inside(sf, root=root) -> bool:
            return root == "." or sf.rel.startswith(root + "/")

        match = _VERSION.search(pf.text)
        if not match or not match.group(1).strip():
            continue
        if not any(inside(p) and _STORE.search(p.text) for p in presets):
            continue
        measured += 1
        version = match.group(1).strip()
        line = pf.text[:match.start()].count("\n") + 1
        mine = [c for c in catalogs if inside(c)]
        if not mine:
            findings.append(Finding(
                check_id=_ID, severity=Severity.WARNING,
                message=f"Store-Projekt (Version {version}) ohne „Was ist neu“-Katalog data/whats_new.json.",
                file=pf.rel, line=line, evidence=snippet(pf.lines[line - 1]),
                fix="data/whats_new.json (Version → Katalogschlüssel) anlegen, Fenster nach Update und Store-Text daraus erzeugen.",
                guideline=_GUIDELINE,
            ))
            continue
        for catalog in mine:
            try:
                data = json.loads(catalog.text)
            except ValueError as exc:
                findings.append(Finding(
                    check_id=_ID, severity=Severity.ERROR,
                    message=f"„Was ist neu“-Katalog nicht lesbar: {exc}",
                    file=catalog.rel, line=1, evidence=snippet(catalog.lines[0] if catalog.lines else ""),
                    fix="Gültiges JSON {\"version\": 1, \"releases\": [...]} herstellen.", guideline=_GUIDELINE,
                ))
                continue
            releases = data.get("releases") if isinstance(data, dict) else None
            entry = next((r for r in releases if isinstance(r, dict) and r.get("version") == version), None) \
                if isinstance(releases, list) else None
            items = entry.get("items") if entry else None
            if not isinstance(items, list) or not items:
                findings.append(Finding(
                    check_id=_ID, severity=Severity.ERROR,
                    message=f"Keine „Was ist neu“-Punkte für Version {version} (project.godot) in {catalog.rel}.",
                    file=catalog.rel, line=1, evidence=snippet(f'config/version="{version}"'),
                    fix=f"Eintrag {{\"version\": \"{version}\", \"items\": [Katalogschlüssel]}} ergänzen, Texte in die Lokalisierung.",
                    guideline=_GUIDELINE,
                ))
    if measured == 0:
        return unmeasured(_ID, title, "Kein Godot-Projekt mit Version und iOS-/Android-Export gefunden.", PLATFORM)
    return result_for(_ID, title, findings, measured, "Store-Projekte", PLATFORM)
