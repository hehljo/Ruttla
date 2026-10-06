"""Bounded fresh full-rect sibling overlay check; no general geometry proof."""
from __future__ import annotations
import re
from ruttla.core import Context, CheckResult, Finding, SelfTestCase, Severity, Status, register, result_for, strip_comments, unmeasured
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
        if not re.search(r"(?m)^[ \t]*extends\s+Control\s*$", text):
            continue
        functions = list(re.finditer(r"(?m)^func\s+\w+\([^\n]*", text))
        for i, fn in enumerate(functions):
            body = text[fn.end():functions[i + 1].start() if i + 1 < len(functions) else len(text)]
            if re.search(r"(?m)^[ \t]*(?:if|elif|for|while|match|await)\b", body):
                continue
            nodes = {m[1]: m[2] for m in re.finditer(r"\bvar\s+(\w+)(?:\s*:\s*\w+)?\s*(?::=|=)\s*(HBoxContainer|MarginContainer|Button)\.new\(\)", body)}
            full = {m[1] for m in re.finditer(r"\b(\w+)\.set_anchors_and_offsets_preset\(Control\.PRESET_FULL_RECT\)", body)}
            siblings = [(m[1], m.start()) for m in re.finditer(r"(?m)^[ \t]*(?:self\.)?add_child\((\w+)\)\s*$", body)]
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
                    assignments = re.findall(r"(?m)^[ \t]*" + re.escape(overlay) + r"\.mouse_filter\s*=\s*([^\n]+)", body)
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


# --- HUD-Fläche schluckt den Weltklick --------------------------------------
# Gemessen mit Godot 4.7.1 headless (06.10.2026): Klick per Viewport.push_input
# auf eine Fläche über einem Node mit _unhandled_input. STOP (0) verschluckt
# ihn, PASS (1) und IGNORE (2) lassen ihn durch. Standardfilter STOP haben
# Control, Panel, PanelContainer, ColorRect, RichTextLabel, ProgressBar;
# Label, NinePatchRect = IGNORE; Container, TextureRect = PASS.
HUD_ID = "godot.hud_blocks_world_click"
HUD_TITLE = "Dekorative HUD-Fläche mit Standardfilter STOP verschluckt den Weltklick"
STOP_DEFAULT = ("Control", "Panel", "PanelContainer", "ColorRect", "RichTextLabel", "ProgressBar")
_STOP_ALT = "|".join(STOP_DEFAULT)
_WORLD_CLICK = re.compile(r"(?m)^func\s+_unhandled_input\s*\([^\n]*\n((?:[ \t]+[^\n]*\n|[ \t]*\n)*)")
_CREATE = re.compile(r"(?m)^[ \t]*(?:var\s+)?(\w+)(?:\s*:\s*\w+)?\s*:?=\s*(" + _STOP_ALT + r")\.new\(\)")
_TSCN_NODE = re.compile(r'(?m)^\[node name="([^"]+)" type="(' + _STOP_ALT + r')"[^\n]*\]\n((?:(?!\[)[^\n]*\n?)*)')
_TSCN_SCRIPT = re.compile(r'(?m)^\[ext_resource[^\n]*type="Script"[^\n]*path="res://([^"]+)"')

HUD_BASE = """extends Node2D
func _build_ui() -> void:
\tvar layer := CanvasLayer.new()
\tadd_child(layer)
\tvar panel := PanelContainer.new()
\tpanel.mouse_filter = Control.MOUSE_FILTER_IGNORE
\tlayer.add_child(panel)
func _unhandled_input(event: InputEvent) -> void:
\tif event is InputEventMouseButton and event.pressed:
\t\t_accuse(event.position)
"""
HUD_TSCN = """[gd_scene format=3]
[ext_resource type="Script" path="res://scripts/world.gd" id="1"]
[node name="World" type="Node2D"]
script = ExtResource("1")
[node name="Hud" type="CanvasLayer" parent="."]
[node name="Panel" type="PanelContainer" parent="Hud"]
offset_right = 360.0
mouse_filter = 2
"""


def _world_click_files(ctx: Context) -> set[str]:
    found = set()
    for sf in _gd(ctx):
        for m in _WORLD_CLICK.finditer(strip_comments(sf.text, sf.ext)):
            if re.search(r"InputEventMouseButton|MOUSE_BUTTON_", m.group(1)):
                found.add(sf.rel)
    return found


@register(
    HUD_ID, HUD_TITLE,
    platform=PLATFORM, severity=Severity.WARNING, guideline=GUIDELINE,
    references=[REFERENCE, "https://docs.godotengine.org/en/stable/tutorials/inputs/inputevent.html"],
    rationale="Belegt (Drink-and-Hide DH003-LL-015): ein dekoratives PanelContainer im HUD fing den "
              "Anklage-Klick ab, bevor er _unhandled_input erreichte; Bots riefen die Aktion direkt auf "
              "und blieben grün. Gemessen wird nur im Skript bzw. in der Szene mit dem Weltklick-Handler; "
              "ein HUD in einer fremden, instanzierten Szene sieht die Regel nicht.",
    self_tests=[
        SelfTestCase("gesund: IGNORE gesetzt", {"scripts/world.gd": HUD_BASE}, Status.PASS),
        SelfTestCase("defekt: Standardfilter STOP im Skript",
                     {"scripts/world.gd": HUD_BASE.replace("\tpanel.mouse_filter = Control.MOUSE_FILTER_IGNORE\n", "")},
                     Status.FAIL, expect_finding_contains="panel"),
        SelfTestCase("gesund: Label und VBoxContainer lassen durch",
                     {"scripts/world.gd": HUD_BASE.replace("PanelContainer.new()", "Label.new()")
                      .replace("\tpanel.mouse_filter = Control.MOUSE_FILTER_IGNORE\n", "")
                      + "func _hud() -> void:\n\tvar panel2 := PanelContainer.new()\n\tpanel2.mouse_filter = Control.MOUSE_FILTER_PASS\n"},
                     Status.PASS),
        SelfTestCase("gesund: Szene mit mouse_filter = 2",
                     {"scripts/world.gd": "extends Node2D\n" + HUD_BASE.split("\n", 7)[7], "scenes/world.tscn": HUD_TSCN},
                     Status.PASS),
        SelfTestCase("defekt: Szene ohne mouse_filter",
                     {"scripts/world.gd": "extends Node2D\n" + HUD_BASE.split("\n", 7)[7],
                      "scenes/world.tscn": HUD_TSCN.replace("mouse_filter = 2\n", "")},
                     Status.FAIL, expect_finding_contains="Panel"),
        SelfTestCase("ungemessen: kein Weltklick über _unhandled_input",
                     {"scripts/world.gd": HUD_BASE.replace("_unhandled_input", "_input")}, Status.UNMEASURED),
        SelfTestCase("gesund: fremde Szene ohne Handler-Skript zählt nicht",
                     {"scripts/world.gd": HUD_BASE, "scenes/menu.tscn": HUD_TSCN.replace("scripts/world.gd", "scripts/menu.gd").replace("mouse_filter = 2\n", "")},
                     Status.PASS),
    ],
)
def check_hud_blocks_world_click(ctx: Context) -> CheckResult:
    handlers = _world_click_files(ctx)
    if not handlers:
        return unmeasured(HUD_ID, HUD_TITLE, "Kein Mausklick in _unhandled_input — es gibt keinen Weltklick, den ein HUD verschlucken könnte.", PLATFORM)
    findings, units = [], 0
    for sf in _gd(ctx):
        if sf.rel not in handlers:
            continue
        text = strip_comments(sf.text, sf.ext)
        for m in _CREATE.finditer(text):
            units += 1
            name, kind = m.group(1), m.group(2)
            if re.search(r"\b" + re.escape(name) + r"\.(?:mouse_filter\s*=|set_mouse_filter\()", text):
                continue
            line = text.count("\n", 0, m.start()) + 1
            findings.append(_hud_finding(sf.rel, line, f"{name} := {kind}.new()", kind))
    for sf in ctx.files(".tscn"):
        scripts = set(_TSCN_SCRIPT.findall(sf.text))
        if not any(h.endswith(s) for h in handlers for s in scripts):
            continue
        for m in _TSCN_NODE.finditer(sf.text):
            units += 1
            if re.search(r"(?m)^mouse_filter\s*=", m.group(3)):
                continue
            line = sf.text.count("\n", 0, m.start()) + 1
            findings.append(_hud_finding(sf.rel, line, f'{m.group(1)} ({m.group(2)})', m.group(2)))
    return result_for(HUD_ID, HUD_TITLE, findings, units, "STOP-Controls neben einem Weltklick-Handler", PLATFORM)


def _hud_finding(rel: str, line: int, evidence: str, kind: str) -> Finding:
    return Finding(HUD_ID, Severity.WARNING,
        f"{kind} hat den Standardfilter STOP und verschluckt jeden Klick auf seiner Fläche, bevor "
        "_unhandled_input ihn sieht — die Weltaktion darunter kommt nie an.",
        file=rel, line=line, evidence=evidence,
        fix="Dekorative Flächen auf Control.MOUSE_FILTER_IGNORE setzen (Szene: mouse_filter = 2); "
            "STOP bewusst nur für Flächen, die Klicks abfangen sollen. Klick per Viewport.push_input testen, "
            "nicht nur die Aktion direkt aufrufen.",
        guideline=GUIDELINE)
