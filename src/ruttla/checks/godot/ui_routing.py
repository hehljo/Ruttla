"""Godot UI interaction and event-routing checks.

Detects buttons masked by overlapping containers consuming mouse/touch events.
"""

from __future__ import annotations

import re

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    register,
    result_for,
    SelfTestCase,
    Severity,
    snippet,
    Status,
    unmeasured,
)

PLATFORM = "godot"


@register(
    "godot.ui_container_masks_buttons",
    "Übergeordneter Control/MarginContainer ohne mouse_filter = PASS blockiert Klicks auf Buttons",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § UI & Control-Nodes",
    self_tests=[
        SelfTestCase(
            name="MarginContainer blockiert darunterliegende Buttons",
            files={
                "scripts/ui/menu.gd": (
                    "extends Control\n"
                    "func _ready():\n"
                    "    var top = HBoxContainer.new()\n"
                    "    add_child(top)\n"
                    "    var margin = MarginContainer.new()\n"
                    "    add_child(margin)\n"
                    "    var btn = Button.new()\n"
                    "    top.add_child(btn)\n"
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="Top-Bar",
        ),
        SelfTestCase(
            name="Saubere Z-Index oder Mouse-Filter Trennung",
            files={
                "scripts/ui/menu.gd": (
                    "extends Control\n"
                    "func _ready():\n"
                    "    var top = HBoxContainer.new()\n"
                    "    top.z_index = 10\n"
                    "    add_child(top)\n"
                    "    var margin = MarginContainer.new()\n"
                    "    margin.mouse_filter = Control.MOUSE_FILTER_PASS\n"
                    "    add_child(margin)\n"
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_ui_container_masks_buttons(ctx: Context) -> CheckResult:
    """Wenn in Godot Controls oder MarginContainer vollflächig über andere
    interaktive Elemente (wie Top-Bars oder Buttons) gelegt werden, fängt Godots
    Event-System Touch-/Mausevents standardmäßig ab (MOUSE_FILTER_STOP).
    Dies führt dazu, dass sichtbare Buttons nicht mehr klickbar sind ('tote Buttons').
    Lösung: Container auf mouse_filter = MOUSE_FILTER_PASS setzen oder z_index erhöhen."""
    title = "Überdeckende UI-Container blockieren Buttons"
    gd_files = [sf for sf in ctx.all_files() if sf.rel.endswith(".gd") and "ui" in sf.rel]
    if not gd_files:
        return unmeasured("godot.ui_container_masks_buttons", title,
                          "Keine UI-GDScript-Dateien gefunden.", PLATFORM)

    findings: list[Finding] = []
    measured = 0

    full_rect_pat = re.compile(r'\b(?:set_anchors_and_offsets_preset|full_rect)\b')
    margin_new = re.compile(r'(\w+)\s*:=\s*MarginContainer\.new\(\)')
    top_bar_new = re.compile(r'(\w+)\s*:=\s*HBoxContainer\.new\(\)')

    for sf in gd_files:
        text = sf.text
        if "top_bar" in text and "margin" in text:
            measured += 1
            # Prüfe, ob MarginContainer ohne MOUSE_FILTER_PASS und top_bar ohne z_index/PASS existiert
            has_margin_pass = "margin.mouse_filter = Control.MOUSE_FILTER_PASS" in text or "margin.mouse_filter = 1" in text
            has_top_z = "top_bar.z_index" in text
            if not has_margin_pass and not has_top_z:
                findings.append(Finding(
                    check_id="godot.ui_container_masks_buttons",
                    severity=Severity.ERROR,
                    message="MarginContainer überdeckt Top-Bar ohne 'mouse_filter = Control.MOUSE_FILTER_PASS' — Buttons in der Top-Bar empfangen keine Klicks.",
                    file=sf.rel,
                    line=1,
                    evidence=snippet(text.splitlines()[0]),
                    fix="Setze 'margin.mouse_filter = Control.MOUSE_FILTER_PASS' oder hebe die Top-Bar mit 'top_bar.z_index = 10' an.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § UI & Control-Nodes",
                ))

    return result_for("godot.ui_container_masks_buttons", title, findings, measured,
                      "UI-Dateien mit Top-Bar", PLATFORM)
