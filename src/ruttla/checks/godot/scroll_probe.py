"""Project-wide scroll-list/probe presence check; target code is never run.

Python is necessary: scene ancestry, script-defined button classes and the
absence of a call in OTHER files of the nearest project.godot cannot be
expressed by the per-file declarative rule format. This is an advisory about
source coverage, never proof that a swipe passed or that every list is tested.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, SourceFile, Status,
    register, result_for, snippet, unmeasured,
)

ID = "godot.scroll_without_drag_probe"
TITLE = "Godot-Scrollliste ohne Aufruf einer Wischprobe"
GUIDELINE = "CODE_QUALITY_GUIDELINES_GAMEDEV.md § UI & Control-Nodes"
BUTTONS = {"BaseButton", "Button", "TextureButton", "CheckButton", "CheckBox",
           "OptionButton", "MenuButton", "LinkButton", "PanelContainer"}
_NEW = re.compile(r"\b([A-Za-z_]\w*)[ \t]*\.[ \t]*new[ \t]*\(")
_CALL = re.compile(r"\b(?:drag_scrolls|reach_by_drag)[ \t\r\n]*\(")
_DECL = re.compile(r"\bfunc[ \t]+(?:drag_scrolls|reach_by_drag)[ \t]*$")
_NODE = re.compile(r'^\[node[ \t]+([^\n]*)\][ \t]*$', re.M)
_ATTR = re.compile(r'\b(name|type|parent)[ \t]*=[ \t]*"([^"\n]*)"')

PROJECT = "[application]\nconfig/name=\"Scroll fixture\"\n"
SCENE = ('[gd_scene format=3]\n[node name="Root" type="Control"]\n'
         '[node name="List" type="ScrollContainer" parent="."]\n'
         '[node name="Rows" type="VBoxContainer" parent="List"]\n'
         '[node name="Buy" type="Button" parent="List/Rows"]\n')
CALL = "func test_scroll():\n\tawait RuttlaScrollProbe.drag_scrolls(scroll, origin)\n"


def _code(text: str) -> str:
    """Mask strings/comments, including triple quotes; preserve offsets/lines."""
    out = list(text)
    i = 0
    while i < len(text):
        start = i
        if text[i] == "#":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text[i] in "\"'":
            quote = text[i] * (3 if text.startswith(text[i] * 3, i) else 1)
            i += len(quote)
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text.startswith(quote, i):
                    i += len(quote)
                    break
                else:
                    i += 1
        else:
            i += 1
            continue
        for k in range(start, min(i, len(text))):
            if out[k] != "\n":
                out[k] = " "
    return "".join(out)


def _has_call(body: str) -> bool:
    # The shipped probe calls drag_scrolls internally. Installing it alone is
    # not application coverage; neither are method definitions or docstrings.
    if re.search(r"^class_name[ \t]+RuttlaScrollProbe\b", body, re.M):
        return False
    for match in _CALL.finditer(body):
        before = body[body.rfind("\n", 0, match.start()) + 1:match.start()]
        if not _DECL.search(before + match.group().split("(")[0].rstrip()):
            return True
    return False


def _button_types(scripts: list[tuple[SourceFile, str]]) -> set[str]:
    types = set(BUTTONS)
    parents = []
    for _, body in scripts:
        name = re.search(r"^class_name[ \t]+(\w+)", body, re.M)
        base = re.search(r"^extends[ \t]+(\w+)", body, re.M)
        if name and base:
            parents.append((name[1], base[1]))
    while True:
        derived = {name for name, base in parents if base in types} - types
        if not derived:
            return types
        types.update(derived)


def _scene_candidates(sf: SourceFile, types: set[str], dynamic: bool) -> list[int]:
    nodes = [(m, dict(_ATTR.findall(m[1]))) for m in _NODE.finditer(sf.text)]
    candidates = []
    for match, attrs in nodes:
        if attrs.get("type") != "ScrollContainer":
            continue
        parent = attrs.get("parent")
        path = "" if parent is None else (
            attrs.get("name", "") if parent == "." else parent + "/" + attrs.get("name", ""))
        has_button = any(
            child.get("type") in types and "parent" in child
            and (not path or child["parent"] == path or child["parent"].startswith(path + "/"))
            for _, child in nodes
        )
        if has_button or dynamic:
            candidates.append(match.start())
    return candidates


@register(
    ID, TITLE, platform="godot", severity=Severity.WARNING, guideline=GUIDELINE,
    references=("https://docs.godotengine.org/en/stable/classes/class_scrollcontainer.html",
                "https://docs.godotengine.org/en/stable/classes/class_control.html#enum-control-mousefilter"),
    rationale="Buttons and cards can retain touch drags inside scroll lists. "
              "Programmatic visibility is not a swipe. This bounded project-wide "
              "source check asks for a drag_scrolls/reach_by_drag call, not runtime success.",
    self_tests=[
        SelfTestCase("gesund: Szenenliste mit Wischaufruf", {
            "project.godot": PROJECT, "menu.tscn": SCENE, "tests/swipe.gd": CALL}, Status.PASS),
        SelfTestCase("gesund: verdecktes Ziel per Wischen", {
            "project.godot": PROJECT, "menu.tscn": SCENE,
            "tests/swipe.gd": CALL.replace("drag_scrolls", "reach_by_drag")}, Status.PASS),
        SelfTestCase("defekt: keine Wischprobe", {
            "project.godot": PROJECT, "menu.tscn": SCENE}, Status.FAIL),
        SelfTestCase("defekt: nur programmatisch sichtbar", {
            "project.godot": PROJECT, "menu.tscn": SCENE,
            "tests/swipe.gd": CALL.replace("drag_scrolls", "ensure_control_visible")}, Status.FAIL),
        SelfTestCase("defekt: dynamische Scrollliste", {
            "project.godot": PROJECT,
            "menu.gd": "var list = ScrollContainer.new()\nvar card = PanelContainer.new()\n"}, Status.FAIL),
        SelfTestCase("defekt: eigener Button", {
            "project.godot": PROJECT, "menu.gd": "var list = ScrollContainer.new()\nvar b = Buy.new()\n",
            "buy.gd": "class_name Buy\nextends Button\n"}, Status.FAIL),
        SelfTestCase("defekt: installiert ist nicht aufgerufen", {
            "project.godot": PROJECT, "menu.tscn": SCENE,
            "addons/ruttla_probes/scroll_probe.gd": "class_name RuttlaScrollProbe\n"
            "static func drag_scrolls(s, p):\n\tpass\n"
            "static func reach_by_drag(s, p):\n\tawait drag_scrolls(s, p)\n"}, Status.FAIL),
        SelfTestCase("defekt: Kommentar und String sind kein Aufruf", {
            "project.godot": PROJECT, "menu.tscn": SCENE,
            "test.gd": '# drag_scrolls(s, p)\nvar text = "reach_by_drag(s, p)"\n'}, Status.FAIL),
        SelfTestCase("defekt: Methodendefinition ist kein Aufruf", {
            "project.godot": PROJECT, "menu.tscn": SCENE,
            "test.gd": "static func drag_scrolls(s, p):\n\tpass\n"}, Status.FAIL),
        SelfTestCase("ungemessen: keine Scrollliste", {
            "project.godot": PROJECT, "menu.gd": "var b = Button.new()\n"}, Status.UNMEASURED),
        SelfTestCase("ungemessen: reine Textliste", {
            "project.godot": PROJECT, "menu.tscn": SCENE.replace('type="Button"', 'type="Label"')},
                     Status.UNMEASURED),
        SelfTestCase("ungemessen: kein Godot-Projekt", {"menu.tscn": SCENE}, Status.UNMEASURED),
    ],
)
def check_scroll_without_drag_probe(ctx: Context) -> CheckResult:
    files = ctx.all_files()
    roots = sorted((str(PurePosixPath(sf.rel).parent) for sf in files
                    if PurePosixPath(sf.rel).name == "project.godot"), key=len, reverse=True)
    sources = ctx.files(".gd", ".tscn")
    groups: dict[str, list[SourceFile]] = {root: [] for root in roots}
    for sf in sources:
        owner = next((root for root in roots if root == "." or sf.rel.startswith(root + "/")), None)
        if owner is not None:
            groups[owner].append(sf)
    findings = []
    measured = 0
    for root, members in groups.items():
        scripts = [(sf, _code(sf.text)) for sf in members if sf.ext == ".gd"]
        types = _button_types(scripts)
        # Intentionally project-wide: dynamic construction need not occur in
        # the same file as the ScrollContainer. No parenting/data-flow claim.
        dynamic = any(m[1] in types for _, body in scripts for m in _NEW.finditer(body))
        candidates = [(sf, offset) for sf in members if sf.ext == ".tscn"
                      for offset in _scene_candidates(sf, types, dynamic)]
        if dynamic:
            candidates.extend((sf, m.start()) for sf, body in scripts for m in _NEW.finditer(body)
                              if m[1] == "ScrollContainer")
        measured += len(candidates)
        if not candidates or any(_has_call(body) for _, body in scripts):
            continue
        for sf, offset in candidates:
            line = sf.line_of(offset)
            findings.append(Finding(
                check_id=ID, severity=Severity.WARNING, file=sf.rel, line=line,
                evidence=snippet(sf.lines[line - 1]),
                message="Scrollliste mit Buttons/Karten, aber kein Aufruf von drag_scrolls() "
                        "oder reach_by_drag() im selben Godot-Projekt.",
                fix="RuttlaScrollProbe im Projekt aktualisieren und im Test auf einem sichtbaren "
                    "Button/einer Karte wischen; Scrollbewegung, erreichbares Ziel und ausbleibende "
                    "Fachaktion prüfen. ensure_control_visible() ersetzt keinen Wischtest.",
                guideline=GUIDELINE,
            ))
    if not measured:
        return unmeasured(ID, TITLE, "Keine Scrollliste mit statischen oder dynamischen Buttons/Karten "
                          "innerhalb eines project.godot gefunden.", "godot")
    return result_for(ID, TITLE, findings, measured, "Scrolllisten-Kandidaten", "godot")
