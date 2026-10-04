"""Godot UI layout checks with native-source and runtime counterprobes."""

from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, snippet, strip_comments,
)
from ._common import PLATFORM, _gd

# Native rationale: Control::_set_anchors_layout_preset returns in Position mode.
# https://github.com/godotengine/godot/blob/master/scene/gui/control.cpp#L1021

@register(
    "godot.fresh_control_editor_anchor_preset",
    "Full-Rect-Editorpreset an einem neu erzeugten Control im Positionsmodus",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § UI & Control-Nodes",
    self_tests=[
        SelfTestCase(
            name="frische Textzeile mit wirkungslosem Editorpreset",
            files={"src/ui.gd": "extends Control\nfunc create():\n\tvar row := HBoxContainer.new()\n\trow.anchors_preset = Control.PRESET_FULL_RECT\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="echte Anker und Offsets anwenden",
            files={"src/ui.gd": "extends Control\nfunc create():\n\tvar row := HBoxContainer.new()\n\trow.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Ankermodus vor Editorpreset ist wirksam",
            files={"src/ui.gd": "extends Control\nfunc create():\n\tvar row := HBoxContainer.new()\n\trow.layout_mode = 1\n\trow.anchors_preset = Control.PRESET_FULL_RECT\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="eigene gleichnamige Eigenschaft ist kein Control",
            files={"src/ui.gd": "extends Node\nfunc create():\n\tvar row := CustomData.new()\n\trow.anchors_preset = Control.PRESET_FULL_RECT\n"},
            expect=Status.UNMEASURED,
        ),
        SelfTestCase(
            name="Szenen-Editorpreset zusammen mit realen Ankern",
            files={"src/ui.gd": "extends Control\n", "scenes/ui.tscn": '[node name="Row" type="HBoxContainer"]\nanchors_preset = 15\nanchor_right = 1.0\nanchor_bottom = 1.0\n'},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_fresh_control_editor_anchor_preset(ctx: Context) -> CheckResult:
    """Control defaults to Position mode. Its internal editor preset setter
    returns without applying anchors in that mode. Deliberately only measure
    an immediately following assignment on a known, freshly created builtin:
    existing nodes, intervening setup and custom classes need runtime evidence.
    """
    check_id = "godot.fresh_control_editor_anchor_preset"
    title = "Full-Rect-Editorpreset an neuem Control im Positionsmodus"
    native_types = "Control|HBoxContainer|VBoxContainer|MarginContainer|GridContainer|PanelContainer|Button|Label|TextureRect|ColorRect|ScrollContainer|Panel"
    creation = re.compile(
        r"(?m)^[ \t]*var[ \t]+(?P<node>\w+)(?:[ \t]*:[ \t]*\w+)?"
        r"[ \t]*(?::=|=)[ \t]*(?:" + native_types + r")\.new\(\)[ \t]*$"
    )
    invalid = re.compile(creation.pattern + r"\n(?:[ \t]*\n)*[ \t]*(?P<assignment>(?P=node)\.anchors_preset[ \t]*=[ \t]*Control\.PRESET_FULL_RECT\b)")
    findings: list[Finding] = []
    measured = 0
    for sf in _gd(ctx):
        body = strip_comments(sf.text, sf.ext)
        if re.search(r"(?m)^\s*@tool\b", body):
            continue
        measured += len(list(creation.finditer(body)))
        for match in invalid.finditer(body):
            line = body.count("\n", 0, match.start("assignment")) + 1
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message="anchors_preset wird beim neuen Control im Positionsmodus ignoriert; Full Rect setzt hier keine Laufzeitanker.",
                file=sf.rel, line=line, evidence=snippet(sf.lines[line - 1]),
                fix="set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT) verwenden und die Textbreite im echten Layout prüfen.",
                guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § UI & Control-Nodes",
            ))
    if measured == 0:
        return unmeasured(check_id, title, "Keine unmittelbar prüfbaren neuen nativen Controls gefunden.", PLATFORM)
    return result_for(check_id, title, findings, measured, "neue native Controls", PLATFORM)
