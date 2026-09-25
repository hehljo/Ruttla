"""Mobile and export checks for Godot."""

from __future__ import annotations

import re

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


@register(
    "godot.mobile_renderer_forward_plus",
    "Forward+-Renderer für Mobile konfiguriert (Forward+ läuft nicht auf iOS/Android)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Mobile Rendering",
    self_tests=[
        SelfTestCase(
            name="Forward+ als Mobile-Renderer",
            files={
                "project.godot": (
                    '[rendering]\n'
                    'renderer/rendering_method.mobile="forward_plus"\n'
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="forward_plus",
        ),
        SelfTestCase(
            name="Sauberer Mobile-Renderer",
            files={
                "project.godot": (
                    '[rendering]\n'
                    'renderer/rendering_method.mobile="mobile"\n'
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_mobile_renderer_forward_plus(ctx: Context) -> CheckResult:
    """Godot 4 unterstützt Forward+ ausschließlich auf Desktop-Plattformen.
    Wird Forward+ für mobile Targets konfiguriert, stürzt die App auf iOS/Android ab
    oder fällt unkontrolliert zurück."""
    title = "Forward+-Renderer für Mobile konfiguriert"
    project_files = ctx.files_named("project.godot")
    if not project_files:
        return unmeasured("godot.mobile_renderer_forward_plus", title,
                          "Keine project.godot-Datei gefunden.", PLATFORM)
    pat = re.compile(r'rendering_method(?:\.mobile)?\s*=\s*"forward_plus"')
    findings: list[Finding] = []
    measured = 0
    for pf in project_files:
        for idx, line in enumerate(pf.lines, start=1):
            if "rendering_method.mobile" in line and pat.search(line):
                measured += 1
                findings.append(Finding(
                    check_id="godot.mobile_renderer_forward_plus",
                    severity=Severity.ERROR,
                    message="renderer/rendering_method.mobile ist auf 'forward_plus' gesetzt — Forward+ läuft nicht auf iOS/Android.",
                    file=pf.rel,
                    line=idx,
                    evidence=snippet(line),
                    fix="Auf 'mobile' oder 'gl_compatibility' umstellen.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Mobile Rendering",
                ))
            elif "rendering_method.mobile" in line:
                measured += 1

    if measured == 0:
        return unmeasured("godot.mobile_renderer_forward_plus", title,
                          "Keine rendering_method.mobile-Konfiguration gefunden.", PLATFORM)
    return result_for("godot.mobile_renderer_forward_plus", title, findings, measured,
                      "Mobile-Renderer-Konfigurationen", PLATFORM)


@register(
    "godot.mobile_orientation_mismatch",
    "Handheld-Orientierung passt nicht zum Viewport (Verzerrung/Black Bars auf Mobile)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Mobile Display",
    self_tests=[
        SelfTestCase(
            name="Portrait-Modus mit Landscape-Viewport",
            files={
                "project.godot": (
                    '[display]\n'
                    'window/size/viewport_width=1920\n'
                    'window/size/viewport_height=1080\n'
                    'window/handheld/orientation=1\n'
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="Portrait-Orientierung",
        ),
        SelfTestCase(
            name="Portrait-Modus mit Portrait-Viewport",
            files={
                "project.godot": (
                    '[display]\n'
                    'window/size/viewport_width=1080\n'
                    'window/size/viewport_height=1920\n'
                    'window/handheld/orientation=1\n'
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_mobile_orientation_mismatch(ctx: Context) -> CheckResult:
    """Prüft, ob die Orientierung (Portrait vs Landscape) zu den konfigurierten
    Viewport-Dimensionen passt."""
    title = "Handheld-Orientierung passt nicht zum Viewport"
    project_files = ctx.files_named("project.godot")
    if not project_files:
        return unmeasured("godot.mobile_orientation_mismatch", title,
                          "Keine project.godot-Datei gefunden.", PLATFORM)

    findings: list[Finding] = []
    measured = 0

    width_pat = re.compile(r'viewport_width\s*=\s*(\d+)')
    height_pat = re.compile(r'viewport_height\s*=\s*(\d+)')
    orient_pat = re.compile(r'orientation\s*=\s*([0-9a-zA-Z_]+)')

    for pf in project_files:
        width = None
        height = None
        orient = None
        orient_line = 1

        for idx, line in enumerate(pf.lines, start=1):
            wm = width_pat.search(line)
            if wm:
                width = int(wm.group(1))
            hm = height_pat.search(line)
            if hm:
                height = int(hm.group(1))
            om = orient_pat.search(line)
            if om:
                orient = om.group(1).strip('"')
                orient_line = idx

        if orient is not None and width is not None and height is not None:
            measured += 1
            # 1 = portrait, 3 = reverse_portrait, 5 = sensor_portrait
            is_portrait = orient in ("1", "3", "5", "portrait", "reverse_portrait", "sensor_portrait")
            # 0 = landscape, 2 = reverse_landscape, 4 = sensor_landscape
            is_landscape = orient in ("0", "2", "4", "landscape", "reverse_landscape", "sensor_landscape")

            if is_portrait and width > height:
                findings.append(Finding(
                    check_id="godot.mobile_orientation_mismatch",
                    severity=Severity.WARNING,
                    message=f"Portrait-Orientierung ('{orient}') konfiguriert, aber Viewport ist breiter als hoch ({width}x{height}).",
                    file=pf.rel,
                    line=orient_line,
                    evidence=snippet(pf.lines[orient_line - 1]),
                    fix="Viewport-Dimensionen vertauschen (Breite < Höhe) oder Orientierung anpassen.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Mobile Display",
                ))
            elif is_landscape and height > width:
                findings.append(Finding(
                    check_id="godot.mobile_orientation_mismatch",
                    severity=Severity.WARNING,
                    message=f"Landscape-Orientierung ('{orient}') konfiguriert, aber Viewport ist höher als breit ({width}x{height}).",
                    file=pf.rel,
                    line=orient_line,
                    evidence=snippet(pf.lines[orient_line - 1]),
                    fix="Viewport-Dimensionen vertauschen (Breite > Höhe) oder Orientierung anpassen.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Mobile Display",
                ))

    if measured == 0:
        return unmeasured("godot.mobile_orientation_mismatch", title,
                          "Keine Handheld-Orientierung mit Viewport-Größen gefunden.", PLATFORM)
    return result_for("godot.mobile_orientation_mismatch", title, findings, measured,
                      "Orientierungs-Konfigurationen", PLATFORM)


@register(
    "godot.ios_export_preset_missing_signing",
    "iOS-Exportpreset ohne Team-ID oder Bundle-Identifier (bricht Xcode Cloud / Signing ab)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 22",
    self_tests=[
        SelfTestCase(
            name="iOS-Preset ohne Team-ID",
            files={
                "export_presets.cfg": (
                    '[preset.0]\n'
                    'name="iOS"\n'
                    'platform="iOS"\n'
                    '[preset.0.options]\n'
                    'application/bundle_identifier="com.example.app"\n'
                    'application/app_store_team_id=""\n'
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="app_store_team_id",
        ),
        SelfTestCase(
            name="Gültiges iOS-Preset",
            files={
                "export_presets.cfg": (
                    '[preset.0]\n'
                    'name="iOS"\n'
                    'platform="iOS"\n'
                    '[preset.0.options]\n'
                    'application/bundle_identifier="com.example.app"\n'
                    'application/app_store_team_id="ABCDE12345"\n'
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_ios_export_preset_signing(ctx: Context) -> CheckResult:
    """Prüft, ob für das iOS-Exportpreset in export_presets.cfg sowohl eine gültige
    Team-ID als auch ein Bundle-Identifier hinterlegt sind. Fehlt eines davon, bricht
    Godot den Export ab oder Xcode Cloud scheitert beim automatischen Signieren."""
    title = "iOS-Exportpreset ohne Team-ID oder Bundle-Identifier"
    preset_files = ctx.files_named("export_presets.cfg")
    if not preset_files:
        return unmeasured("godot.ios_export_preset_missing_signing", title,
                          "Keine export_presets.cfg-Datei gefunden.", PLATFORM)

    findings: list[Finding] = []
    measured = 0
    ios_preset_pat = re.compile(r'platform="iOS"')
    team_id_pat = re.compile(r'application/app_store_team_id="([^"]*)"')
    bundle_id_pat = re.compile(r'application/bundle_identifier="([^"]*)"')

    for pf in preset_files:
        in_ios_section = False
        team_id = None
        bundle_id = None
        ios_line = 1

        for idx, line in enumerate(pf.lines, start=1):
            if line.startswith("[preset.") and "options" not in line:
                if in_ios_section:
                    break
                in_ios_section = False

            if ios_preset_pat.search(line):
                in_ios_section = True
                ios_line = idx

            if in_ios_section:
                tm = team_id_pat.search(line)
                if tm:
                    team_id = tm.group(1).strip()
                bm = bundle_id_pat.search(line)
                if bm:
                    bundle_id = bm.group(1).strip()

        if in_ios_section:
            measured += 1
            if not team_id:
                findings.append(Finding(
                    check_id="godot.ios_export_preset_missing_signing",
                    severity=Severity.ERROR,
                    message="iOS-Preset hat keine 'app_store_team_id' konfiguriert (Pflicht für Signing & Xcode Cloud).",
                    file=pf.rel,
                    line=ios_line,
                    evidence=snippet(pf.lines[ios_line - 1]),
                    fix="application/app_store_team_id auf die 10-stellige Apple Developer Team-ID setzen.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 22",
                ))
            if not bundle_id:
                findings.append(Finding(
                    check_id="godot.ios_export_preset_missing_signing",
                    severity=Severity.ERROR,
                    message="iOS-Preset hat keinen 'bundle_identifier' konfiguriert.",
                    file=pf.rel,
                    line=ios_line,
                    evidence=snippet(pf.lines[ios_line - 1]),
                    fix="application/bundle_identifier auf eine gültige Bundle-ID (z. B. 'com.firma.app') setzen.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 22",
                ))

    if measured == 0:
        return unmeasured("godot.ios_export_preset_missing_signing", title,
                          "Kein iOS-Exportpreset in export_presets.cfg gefunden.", PLATFORM)
    return result_for("godot.ios_export_preset_missing_signing", title, findings, measured,
                      "iOS-Exportpresets", PLATFORM)
