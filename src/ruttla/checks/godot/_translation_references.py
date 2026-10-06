"""Configured Godot CSV references; source only, no target execution.

The TALENT_HP_DESC regression had matching DE/EN catalogs with the
same missing key. Parity cannot catch that. This check follows literal tr()
references, scene text keys and explicit *_key data fields within each nearest
project.godot. Dynamic references and non-CSV catalogs remain unmeasured.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from ruttla.core import (Context, Finding, SelfTestCase, Severity, Status,
                         snippet, strip_comments)

_ID = 'i18n.catalog_key_parity'
_GUIDE = 'CODE_QUALITY_GUIDELINES_GAMEDEV.md § Lokalisierung'
_PROJECT = '[internationalization]\nlocale/translations=PackedStringArray("res://localization/ui.de.translation", "res://localization/ui.en.translation")\n'
_CATALOG = 'keys,de,en\nUI_PLAY,Spielen,Play\nTALENT_HP_DESC,Leben,Health\n'
_REFERENCE = re.compile(
    r'(?:\btr\(\s*|"(?:title|desc|name|unlock)_key"\s*:\s*|^[ \t]*text\s*=\s*)'
    r'"([A-Z][A-Z0-9_]*_[A-Z0-9_]+)"', re.M)


REFERENCE_SELF_TESTS = [
    SelfTestCase(name='Gesunde direkte und datengesteuerte Referenzen', files={
        'project.godot': _PROJECT, 'localization/ui.csv': _CATALOG,
        'menu.gd': 'var d = {"desc_key": "TALENT_HP_DESC"}\nvar t = tr("UI_PLAY")\n'}, expect=Status.PASS),
    SelfTestCase(name='Fehlender direkter Schlüssel', files={
        'project.godot': _PROJECT, 'localization/ui.csv': _CATALOG,
        'menu.gd': 'var t = tr("UI_MISSING")\n'}, expect=Status.FAIL),
    SelfTestCase(name='Fehlender Talenttext trotz Katalogparität', files={
        'project.godot': _PROJECT, 'localization/ui.csv': _CATALOG,
        'menu.gd': 'var d = {"desc_key": "TALENT_HP_MISSING_DESC"}\n'}, expect=Status.FAIL),
    SelfTestCase(name='Fehlender Szenentext', files={
        'project.godot': _PROJECT, 'localization/ui.csv': _CATALOG,
        'menu.tscn': '[node name="Title" type="Label"]\ntext = "UI_MISSING"\n'}, expect=Status.FAIL),
    SelfTestCase(name='Leere Sprachzelle', files={
        'project.godot': _PROJECT, 'localization/ui.csv': 'keys,de,en\nUI_PLAY,Spielen,\n',
        'menu.gd': 'var t = tr("UI_PLAY")\n'}, expect=Status.FAIL),
    SelfTestCase(name='Kommentare definieren keinen UI-Schlüssel', files={
        'project.godot': _PROJECT, 'localization/ui.csv': _CATALOG,
        'menu.gd': '# tr("UI_MISSING")\nvar t = tr("UI_PLAY")\n'}, expect=Status.PASS),
    SelfTestCase(name='Nicht eingebundener Katalog zählt nicht', files={
        'project.godot': '[application]\n', 'localization/ui.csv': _CATALOG,
        'menu.gd': 'var t = tr("UI_PLAY")\n'}, expect=Status.PASS),
    SelfTestCase(name='Dynamischer Schlüssel ungemessen', files={
        'project.godot': _PROJECT, 'localization/ui.csv': _CATALOG,
        'menu.gd': 'var t = tr(definition.desc_key)\n'}, expect=Status.PASS),
    SelfTestCase(name='Defekter CSV-Katalog ungemessen', files={
        'project.godot': _PROJECT, 'localization/ui.csv': 'keys,de,en\nUI_PLAY,Spielen\n',
        'menu.gd': 'var t = tr("UI_PLAY")\n'}, expect=Status.UNMEASURED),
]


def csv_translation_references(ctx: Context, parse_catalog) -> tuple[list[Finding], int]:
    files = {sf.rel: sf for sf in ctx.all_files()}
    projects = sorted((sf for sf in files.values() if PurePosixPath(sf.rel).name == 'project.godot'),
                      key=lambda sf: len(sf.rel), reverse=True)
    findings = []
    measured = 0
    for project in projects:
        prefix = str(PurePosixPath(project.rel).parent)
        prefix = '' if prefix == '.' else prefix + '/'
        catalogs = {}
        invalid = False
        declarations = re.findall(r'^locale/translations\s*=\s*PackedStringArray\(([^\n]*)\)',
                                  strip_comments(project.text, project.ext), re.M)
        for declaration in declarations:
            for relative in re.findall(r'"res://([^"\n]+)"', declaration):
                match = re.fullmatch(r'(.+)\.([a-z]{2,3}(?:[_-][A-Za-z0-9]+)*)\.translation', relative)
                if not match:
                    invalid = True
                    continue
                sf = files.get(prefix + match[1] + '.csv')
                parsed = parse_catalog(sf) if sf else None
                if parsed is None or parsed[2] or match[2] not in parsed[0]:
                    invalid = True
                    continue
                catalogs.setdefault(match[2], set()).update(parsed[0][match[2]])
        if invalid or not catalogs:
            continue
        for sf in files.values():
            if sf.ext not in {'.gd', '.tscn', '.json'} or not sf.rel.startswith(prefix):
                continue
            owner = next((p for p in projects if sf.rel.startswith(
                '' if str(PurePosixPath(p.rel).parent) == '.' else str(PurePosixPath(p.rel).parent) + '/')), None)
            if owner is not project:
                continue
            source = strip_comments(sf.text, sf.ext)
            for match in _REFERENCE.finditer(source):
                key = match[1]
                measured += 1
                missing = [locale for locale, keys in catalogs.items() if key not in keys]
                if missing:
                    line = sf.line_of(match.start())
                    findings.append(Finding(
                        check_id=_ID, severity=Severity.WARNING,
                        message=f'{key} fehlt für eingebundene Sprachen: {", ".join(missing)}.',
                        file=sf.rel, line=line, evidence=snippet(source.splitlines()[line - 1]),
                        fix='Schlüssel in den eingebundenen CSV-Katalogen ergänzen und Engine-Import/gerenderte Anzeige prüfen.',
                        guideline=_GUIDE))
    return findings, measured
