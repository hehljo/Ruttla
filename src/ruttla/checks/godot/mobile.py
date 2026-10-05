"""Mobile and export checks for Godot."""

from __future__ import annotations

import os
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


@register(
    "godot.app_config_missing_support_email",
    "Zentrale AppConfig/Branding-Klasse ohne SUPPORT_EMAIL (Pflicht für Support & TestFlight)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 22",
    self_tests=[
        SelfTestCase(
            name="AppConfig ohne SUPPORT_EMAIL",
            files={
                "scripts/core/app_config.gd": (
                    "class_name AppConfig\n"
                    "extends RefCounted\n\n"
                    'const BRAND_NAME: String = "Test"\n'
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="SUPPORT_EMAIL",
        ),
        SelfTestCase(
            name="AppConfig mit SUPPORT_EMAIL",
            files={
                "scripts/core/app_config.gd": (
                    "class_name AppConfig\n"
                    "extends RefCounted\n\n"
                    'const BRAND_NAME: String = "Test"\n'
                    'const SUPPORT_EMAIL: String = "support@example.com"\n'
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_app_config_support_email(ctx: Context) -> CheckResult:
    """In Godot-Mobilprojekten muss die zentrale App-Konfiguration eine
    SUPPORT_EMAIL definieren, damit Fehlerberichte, Impressum und TestFlight-Metadaten
    immer synchron und gültig sind."""
    title = "Zentrale AppConfig/Branding-Klasse ohne SUPPORT_EMAIL"
    files = ctx.files(".gd")
    if not files:
        return unmeasured("godot.app_config_missing_support_email", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)

    class_pat = re.compile(r"^[ \t]*class_name\s+(AppConfig|Branding)\b", re.MULTILINE)
    email_pat = re.compile(r"^[ \t]*const\s+SUPPORT_EMAIL\s*[:=]", re.MULTILINE)

    findings: list[Finding] = []
    measured = 0

    for sf in files:
        base_name = os.path.basename(sf.rel).lower()
        is_config = bool(class_pat.search(sf.text)) or base_name in ("app_config.gd", "branding.gd")
        if not is_config:
            continue
        measured += 1
        if not email_pat.search(sf.text):
            findings.append(Finding(
                check_id="godot.app_config_missing_support_email",
                severity=Severity.WARNING,
                message=f"'{sf.rel}' definiert keine 'SUPPORT_EMAIL'-Konstante.",
                file=sf.rel,
                line=1,
                evidence=snippet(sf.lines[0]),
                fix="Definiere 'const SUPPORT_EMAIL: String = \"deine@email.de\"' für Support- & Feedback-Routing.",
                guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 22",
            ))

    if measured == 0:
        return unmeasured("godot.app_config_missing_support_email", title,
                          "Keine AppConfig- oder Branding-Klasse gefunden.", PLATFORM)
    return result_for("godot.app_config_missing_support_email", title, findings, measured,
                      "Konfigurationsklassen", PLATFORM)


@register(
    "godot.water_shader_shadows_disabled",
    "Wasser-Shader ohne shadows_disabled (verursacht flackernde Shadow-Acne auf Mobile/Web)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Mobile Rendering",
    self_tests=[
        SelfTestCase(
            name="Wasser-Shader ohne shadows_disabled",
            files={
                "shaders/water.gdshader": (
                    "shader_type spatial;\n"
                    "render_mode blend_mix, depth_draw_opaque;\n"
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="shadows_disabled",
        ),
        SelfTestCase(
            name="Wasser-Shader mit shadows_disabled",
            files={
                "shaders/water.gdshader": (
                    "shader_type spatial;\n"
                    "render_mode blend_mix, depth_draw_opaque, shadows_disabled;\n"
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_water_shader_shadows_disabled(ctx: Context) -> CheckResult:
    """Auf Mobile und WebGL führen Richtungs- und Kaskadenschatten auf gewellten
    Wasseroberflächen zu extremem Tiefenflackern und Shadow-Acne (dunkle Artefakte).
    Wasser-Shader sollten 'shadows_disabled' im render_mode setzen."""
    title = "Wasser-Shader ohne shadows_disabled"
    files = [f for f in ctx.files(".gdshader") if "water" in f.rel.lower() or "river" in f.rel.lower()]
    if not files:
        return unmeasured("godot.water_shader_shadows_disabled", title,
                          "Keine Wasser- oder Fluss-Shader gefunden.", PLATFORM)

    findings: list[Finding] = []
    measured = len(files)
    for sf in files:
        if "shadows_disabled" not in sf.text:
            findings.append(Finding(
                check_id="godot.water_shader_shadows_disabled",
                severity=Severity.WARNING,
                message=f"Wasser-Shader '{sf.rel}' deklariert kein 'shadows_disabled' im render_mode.",
                file=sf.rel,
                line=1,
                evidence=snippet(sf.lines[0]),
                fix="Ergänze 'shadows_disabled' in der 'render_mode'-Zeile, um Shadow-Acne auf Mobile/WebGL zu verhindern.",
                guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Mobile Rendering",
            ))

    return result_for("godot.water_shader_shadows_disabled", title, findings, measured,
                      "Wasser-Shader", PLATFORM)


TOUCH_PROJECT = "[display]\nwindow/size/viewport_width=1080\nwindow/size/viewport_height=1920\nwindow/handheld/orientation=1\n"
TOUCH_BUTTON = '[node name="BackButton" type="Button"]\ncustom_minimum_size = Vector2(200, 164)\n'


@register(
    "godot.mobile_button_touch_target_too_small",
    "Kleine deklarierte Button-Mindesthöhe im 1080p-Portrait-Projekt",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Mobile Display & Orientierung",
    self_tests=[
        SelfTestCase("gesund: deklarierte Untergrenze, kein Gerätenachweis", {"project.godot": TOUCH_PROJECT, "scenes/menu.tscn": TOUCH_BUTTON}, Status.PASS),
        SelfTestCase("gesund: fremdes Desktopprojekt nicht als Mobile prüfen", {"mobile/project.godot": TOUCH_PROJECT, "mobile/scenes/menu.tscn": TOUCH_BUTTON, "desktop/project.godot": "[display]\nwindow/size/viewport_width=800\n", "desktop/scenes/menu.tscn": TOUCH_BUTTON.replace("164", "64")}, Status.PASS),
        SelfTestCase("gesund: verschachteltes Desktopprojekt", {"project.godot": TOUCH_PROJECT, "scenes/menu.tscn": TOUCH_BUTTON, "desktop/project.godot": "[display]\nwindow/size/viewport_width=800\n", "desktop/scenes/menu.tscn": TOUCH_BUTTON.replace("164", "64")}, Status.PASS),
        SelfTestCase("defekt: nur 64 deklarierte Einheiten", {"project.godot": TOUCH_PROJECT, "scenes/menu.tscn": TOUCH_BUTTON.replace("164", "64")}, Status.FAIL, expect_finding_contains="Touch-Ziel"),
        SelfTestCase("defekt: Leerzeichen und Kommentare in Konfiguration", {"project.godot": TOUCH_PROJECT.replace("=", " = ").replace("orientation = 1", "orientation = 1 ; portrait"), "scenes/menu.tscn": TOUCH_BUTTON.replace("164", "64")}, Status.FAIL),
        SelfTestCase("ungemessen: Kommentar ist keine Mobile-Konfiguration", {"project.godot": TOUCH_PROJECT.replace("window/handheld", "; window/handheld"), "scenes/menu.tscn": TOUCH_BUTTON.replace("164", "64")}, Status.UNMEASURED),
        SelfTestCase("ungemessen: Nullminimum erlaubt Containerwachstum", {"project.godot": TOUCH_PROJECT, "scenes/menu.tscn": TOUCH_BUTTON.replace("164", "0")}, Status.UNMEASURED),
        SelfTestCase("ungemessen: kleiner Button außerhalb des Projekts", {"mobile/project.godot": TOUCH_PROJECT, "desktop/scenes/menu.tscn": TOUCH_BUTTON.replace("164", "64")}, Status.UNMEASURED),
    ],
)
def check_mobile_button_touch_target(ctx: Context) -> CheckResult:
    """Inspect declared minima only. Containers/fonts can grow a Control;
    no actual hit region, device density or platform compliance is proved.
    Keep the historical <80 advisory threshold; 96/110 are not universal
    recommendations. Real scaled regions require a bound runtime receipt.
    """
    title = "Kleine deklarierte Button-Mindesthöhe im 1080p-Portrait-Projekt"
    projects = {}
    for pf in ctx.files_named("project.godot"):
        sections = re.split(r"(?m)^[ \t]*\[([^]\n]+)\]\s*$", pf.text)
        display = next((sections[i + 1] for i in range(1, len(sections), 2)
                        if sections[i] == "display"), "")
        portrait = re.search(r"(?m)^[ \t]*window/handheld/orientation\s*=\s*(?:1|portrait)\s*(?:;[^\n]*)?$", display, re.I)
        width = re.search(r"(?m)^[ \t]*window/size/viewport_width\s*=\s*1080\s*(?:;[^\n]*)?$", display)
        projects[pf.rel.rsplit("/", 1)[0] if "/" in pf.rel else ""] = bool(portrait and width)

    tscn_files = ctx.files(".tscn")
    findings: list[Finding] = []
    measured = 0

    node_btn_pat = re.compile(r'\[node\s+name="([^"]+)"\s+type="Button"')
    size_pat = re.compile(r"custom_minimum_size\s*=\s*Vector2\(\s*([\d\.]+)\s*,\s*([\d\.]+)\s*\)")

    for tf in tscn_files:
        owners = [root for root in projects if not root or tf.rel.startswith(root + "/")]
        if not owners or not projects[max(owners, key=len)]:
            continue
        current_btn = None
        for idx, line in enumerate(tf.lines, start=1):
            if line.startswith("[node"):
                m_btn = node_btn_pat.search(line)
                if m_btn:
                    current_btn = m_btn.group(1)
                else:
                    current_btn = None

            if current_btn:
                sm = size_pat.search(line)
                if sm:
                    h = float(sm.group(2))
                    if h <= 0:
                        current_btn = None
                        continue
                    measured += 1
                    if 0 < h < 80.0:
                        findings.append(Finding(
                            check_id="godot.mobile_button_touch_target_too_small",
                            severity=Severity.WARNING,
                            message=(
                                f"Button '{current_btn}' deklariert nur {h:.0f} Godot-Einheiten Mindesthöhe. "
                                "Das kann nach Skalierung ein kleines Touch-Ziel ergeben; die tatsächliche Fläche ist hier ungemessen."
                            ),
                            file=tf.rel,
                            line=idx,
                            evidence=snippet(line),
                            fix="Tatsächliche Trefferfläche nach Skalierung messen: iOS mindestens 44×44pt, Android mindestens 48×48dp. Für Web CSS-Pixel getrennt prüfen; Padding und Containerwachstum berücksichtigen.",
                            guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Mobile Display & Orientierung",
                        ))
                    current_btn = None

    if measured == 0:
        return unmeasured("godot.mobile_button_touch_target_too_small", title,
                          "Keine positiven expliziten Button-Mindesthöhen im 1080p-Portrait-Projekt gefunden; tatsächliche Flächen ungemessen.", PLATFORM)

    return result_for("godot.mobile_button_touch_target_too_small", title, findings, measured,
                      "Mobile-Buttons", PLATFORM)

