"""Bounded fresh full-rect sibling overlay check; no general geometry proof."""
from __future__ import annotations
import re
from ruttla.core import Context, CheckResult, Finding, SelfTestCase, Severity, Status, register, result_for, strip_comments
from ._common import PLATFORM, _gd

GUIDELINE = "CODE_QUALITY_GUIDELINES_GAMEDEV.md § UI & Control-Nodes"
REFERENCE = "https://docs.godotengine.org/en/stable/classes/class_control.html"
BASE = """extends Control
func _ready():
    var bar := HBoxContainer.new()
    bar.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(bar)
    var button := Button.new()
    bar.add_child(button)
    var overlay := MarginContainer.new()
    overlay.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(overlay)
    overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
"""

@register(
    "godot.ui_container_masks_buttons",
    "Vollflächiger Geschwister-Container verdeckt eine Buttonzeile für Eingaben",
    platform=PLATFORM, severity=Severity.ERROR, guideline=GUIDELINE,
    self_tests=[
        SelfTestCase("gesund: IGNORE lässt Eingaben durch", {"scenes/menu.gd": BASE}, Status.PASS),
        SelfTestCase("gesund: Namen sind keine Semantik", {"scenes/menu.gd": BASE.replace("bar", "toolbar").replace("overlay", "decoration")}, Status.PASS),
        SelfTestCase("defekt: STOP fängt Eingaben ab", {"scenes/menu.gd": BASE.replace("MOUSE_FILTER_IGNORE", "MOUSE_FILTER_STOP")}, Status.FAIL),
        SelfTestCase("defekt: PASS geht zum Elternknoten, nicht zum Geschwister", {"scenes/menu.gd": BASE.replace("MOUSE_FILTER_IGNORE", "MOUSE_FILTER_PASS")}, Status.FAIL),
        SelfTestCase("defekt: z_index rettet den Button nicht", {"scenes/menu.gd": BASE.replace("MOUSE_FILTER_IGNORE", "MOUSE_FILTER_STOP").replace("    add_child(bar)", "    bar.z_index = 10\n    add_child(bar)")}, Status.FAIL),
        SelfTestCase("defekt: Standardfilter STOP", {"scenes/menu.gd": BASE.replace("    overlay.mouse_filter = Control.MOUSE_FILTER_IGNORE\n", "")}, Status.FAIL),
        SelfTestCase("ungemessen: Node hat kein Control-Rechteck", {"scenes/menu.gd": BASE.replace("extends Control", "extends Node")}, Status.UNMEASURED),
        SelfTestCase("ungemessen: Geometrie unbekannt", {"scenes/menu.gd": BASE.replace("    overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)\n", "")}, Status.UNMEASURED),
        SelfTestCase("ungemessen: bedingtes Setup", {"scenes/menu.gd": BASE.replace("    add_child(overlay)", "    if enabled:\n        add_child(overlay)")}, Status.UNMEASURED),
        SelfTestCase("ungemessen: Datenobjekt ist kein Control", {"scenes/menu.gd": BASE.replace("MarginContainer.new()", "CustomData.new()")}, Status.UNMEASURED),
        SelfTestCase("ungemessen: nur Kommentare", {"scenes/menu.gd": "extends Control\n# top_bar margin mouse_filter\n"}, Status.UNMEASURED),
        SelfTestCase("ungemessen: Dynamischer Filter", {"scenes/menu.gd": BASE.replace("Control.MOUSE_FILTER_IGNORE", "settings.filter")}, Status.UNMEASURED),
    ],
)
def check_ui_container_masks_buttons(ctx: Context) -> CheckResult:
    check_id = "godot.ui_container_masks_buttons"
    title = "Vollflächiger Geschwister-Container verdeckt Buttonzeile für Eingaben"
    findings, measured = [], 0
    for sf in _gd(ctx):
        text = strip_comments(sf.text, sf.ext)
        if not re.search(r"(?m)^\s*extends\s+Control\s*$", text):
            continue
        functions = list(re.finditer(r"(?m)^func\s+\w+\([^\n]*", text))
        for i, fn in enumerate(functions):
            body = text[fn.end():functions[i + 1].start() if i + 1 < len(functions) else len(text)]
            if re.search(r"(?m)^\s*(?:if|elif|for|while|match|await)\b", body):
                continue
            nodes = {m[1]: m[2] for m in re.finditer(r"\bvar\s+(\w+)(?:\s*:\s*\w+)?\s*(?::=|=)\s*(HBoxContainer|MarginContainer|Button)\.new\(\)", body)}
            full = {m[1] for m in re.finditer(r"\b(\w+)\.set_anchors_and_offsets_preset\(Control\.PRESET_FULL_RECT\)", body)}
            siblings = [(m[1], m.start()) for m in re.finditer(r"(?m)^\s*(?:self\.)?add_child\((\w+)\)\s*$", body)]
            for bar, first in siblings:
                if nodes.get(bar) != "HBoxContainer" or bar not in full:
                    continue
                if not any(re.search(r"\b" + re.escape(bar) + r"\.add_child\(" + re.escape(button) + r"\)", body) for button in nodes if nodes[button] == "Button"):
                    continue
                for overlay, later in siblings:
                    if later <= first or nodes.get(overlay) != "MarginContainer" or overlay not in full:
                        continue
                    if re.search(r"\b" + re.escape(overlay) + r"\.(?:add_child|position|size|offset_\w+|visible|hide|show)\b", body):
                        continue
                    assignments = re.findall(r"(?m)^\s*" + re.escape(overlay) + r"\.mouse_filter\s*=\s*([^\n]+)", body)
                    if len(assignments) > 1 or assignments and assignments[0].strip() not in {"Control.MOUSE_FILTER_STOP", "Control.MOUSE_FILTER_PASS", "Control.MOUSE_FILTER_IGNORE", "0", "1", "2"}:
                        continue
                    measured += 1
                    if assignments and assignments[0].strip() in {"Control.MOUSE_FILTER_IGNORE", "2"}:
                        continue
                    findings.append(Finding(check_id, Severity.ERROR,
                        "Vollflächiger Container nach einer vollflächigen Buttonzeile fängt Geschwister-Eingaben ab. PASS und z_index beheben das nicht.",
                        file=sf.rel, line=text.count("\n", 0, fn.end() + later) + 1,
                        evidence=f"add_child({bar}) → add_child({overlay}); beide Full Rect",
                        fix="Dekorative Überdeckung auf MOUSE_FILTER_IGNORE setzen oder die echte Geschwister-Reihenfolge/Layoutstruktur korrigieren; Klick im Renderer prüfen.", guideline=GUIDELINE))
    return result_for(check_id, title, findings, measured, "explizite Full-Rect-Geschwisterpaare", PLATFORM)
