"""Bounded XML topology check; no code-behind execution or pixel claims.

XML ancestry, active content and Grid rows cannot be represented by the
current declarative regex rule format without treating unrelated scrollbars
as protection. This check therefore uses the standard-library XML parser.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from ruttla.core import (Context, CheckResult, Finding, SelfTestCase, Severity,
                         Status, register, result_for, unmeasured)

NS = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
CID = "dotnet.wpf_dialog_unscrollable_auto_content"
TITLE = "Höhenbegrenzter WPF-Dialog ohne Scrollweg"
GUIDE = "CODE_QUALITY_GUIDELINES_WPF.md § Dialog-Scrollwege"


def _fixture(body: str, attributes: str = 'MaxHeight="650"') -> str:
    return ('<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
            'SizeToContent="Height" ' + attributes + '>' + body + '</Window>')


BODY = ('<Grid><Grid.RowDefinitions><RowDefinition Height="Auto"/>'
        '<RowDefinition Height="Auto"/></Grid.RowDefinitions>'
        '<TextBlock Text="{Binding InfoText}" TextWrapping="Wrap"/>'
        '<Button Grid.Row="1" Content="Übernehmen"/></Grid>')
STACK = '<Border><StackPanel><Image Source="sample.png"/><Button Content="OK"/></StackPanel></Border>'
SCROLL = '<ScrollViewer VerticalScrollBarVisibility="Auto">' + BODY + '</ScrollViewer>'
STAR = ('<Grid><Grid.RowDefinitions><RowDefinition Height="*"/>'
        '<RowDefinition Height="Auto"/></Grid.RowDefinitions>'
        '<ScrollViewer VerticalScrollBarVisibility="Auto"><TextBlock Text="{Binding Info}"/></ScrollViewer>'
        '<Button Grid.Row="1" Content="OK"/></Grid>')


def _children(element: ET.Element) -> list[ET.Element]:
    return [child for child in element if "." not in child.tag.rsplit("}", 1)[-1]
            and child.get("Visibility", "Visible") not in {"Collapsed", "Hidden"}]


def _shape(element: ET.Element) -> str:
    """scroll, unsafe or unknown. Nested list scrollbars do not certify a form."""
    if not element.tag.startswith(NS):
        return "unknown"
    kind = element.tag[len(NS):]
    children = _children(element)
    if kind == "ScrollViewer":
        mode = element.get("VerticalScrollBarVisibility", "Visible")
        if mode in {"Auto", "Visible", "Hidden"}:
            return "scroll"
        if mode == "Disabled" and len(children) == 1:
            return "unsafe" if _shape(children[0]) == "unsafe" else "unknown"
        return "unknown"
    if kind in {"Border", "Decorator"} and len(children) == 1:
        return _shape(children[0])
    if kind == "StackPanel":
        if element.get("Orientation", "Vertical") not in {"Vertical", "Horizontal"}:
            return "unknown"
        states = [_shape(child) for child in children]
        return "unsafe" if states and all(s == "unsafe" for s in states) else "unknown"
    if kind == "Grid":
        definitions = element.find(NS + "Grid.RowDefinitions")
        states = [_shape(child) for child in children]
        if definitions is None or not len(definitions):
            return "unsafe" if states and all(s == "unsafe" for s in states) else "unknown"
        heights = [row.get("Height", "*") for row in definitions]
        if heights and all(height == "Auto" for height in heights):
            return "unsafe" if states and all(s == "unsafe" for s in states) else "unknown"
        # A scrollable star row plus a footer is a structural healthy control only.
        for child, state in zip(children, states):
            try:
                row = int(child.get("Grid.Row", "0"))
            except ValueError:
                continue
            if (state == "scroll" and 0 <= row < len(heights)
                    and heights[row] == "*" and child.get("Grid.RowSpan", "1") == "1"):
                return "scroll"
        return "unknown"
    if kind in {"TextBlock", "Image", "Button", "Label", "TextBox", "ComboBox",
                "CheckBox", "RadioButton", "DatePicker", "Separator", "Rectangle"}:
        return "unsafe"
    return "unknown"


def _may_grow(element: ET.Element) -> bool:
    kind = element.tag.rsplit("}", 1)[-1]
    if kind == "Image":
        return True
    if kind == "TextBlock":
        text = element.get("Text", element.text or "")
        if "{" in text or len(text) > 80 or "\n" in text:
            return True
    return any(_may_grow(child) for child in _children(element))


@register(
    CID, TITLE, platform="dotnet", severity=Severity.WARNING, guideline=GUIDE,
    references=("https://learn.microsoft.com/en-us/dotnet/desktop/wpf/controls/scrollviewer",
                "https://learn.microsoft.com/en-us/dotnet/api/system.windows.window.sizetocontent"),
    rationale=("Reproduziertes Layout: SizeToContent=Height, begrenzte Höhe und ausschließlich "
               "Auto-Zeilen bzw. ein vertikales Formular ohne Scrollweg können dynamische Texte, "
               "Screenshots und Aktionsbuttons abschneiden. XML-Ancestry statt Datei-Grep; "
               "advisory, kein Pixel-/Windows-Nachweis. Benutzerdefinierte Controls, "
               "dynamische Größen und nur lokale Listen-Scrollwege bleiben ungemessen."),
    self_tests=[
        SelfTestCase("gesund: kompletter Inhalt scrollbar", {"Dialog.xaml": _fixture(SCROLL)}, Status.PASS),
        SelfTestCase("gesund: Star-Scrollbereich mit Footer", {"Dialog.xaml": _fixture(STAR)}, Status.PASS),
        SelfTestCase("defekt: Auto-Zeilen ohne Scrollweg", {"Dialog.xaml": _fixture(BODY)}, Status.FAIL),
        SelfTestCase("defekt: Screenshot-Formular ohne Scrollweg", {"Dialog.xaml": _fixture(STACK)}, Status.FAIL),
        SelfTestCase("defekt: vertikales Scrollen deaktiviert", {"Dialog.xaml": _fixture(SCROLL.replace('="Auto"', '="Disabled"', 1))}, Status.FAIL),
        SelfTestCase("defekt: ScrollViewer nur im Template", {"Dialog.xaml": _fixture('<Window.Resources><ControlTemplate x:Key="T" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"><ScrollViewer/></ControlTemplate></Window.Resources>' + BODY)}, Status.FAIL),
        SelfTestCase("defekt: unsichtbarer ScrollViewer schützt nicht", {"Dialog.xaml": _fixture(BODY.replace('<Button', '<ScrollViewer Visibility="Collapsed"/><Button'))}, Status.FAIL),
        SelfTestCase("defekt: nicht resizebares Screenshot-Formular", {"Dialog.xaml": _fixture(STACK, 'ResizeMode="NoResize"')}, Status.FAIL),
        SelfTestCase("defekt: konditionaler Inhalt und verschachtelte Buttonzeile",
                     {"Dialog.xaml": _fixture(BODY.replace('<Button Grid.Row="1" Content="Übernehmen"/>',
                     '<StackPanel Grid.Row="1" Visibility="{Binding ScopeVisibility}"><Grid><Button Content="Abbrechen"/><StackPanel Orientation="Horizontal"><Button Content="Übernehmen"/></StackPanel></Grid></StackPanel>'))}, Status.FAIL),
        SelfTestCase("gesund: kurze statische Button-Auswahl",
                     {"Dialog.xaml": _fixture('<StackPanel Orientation="Horizontal"><Button Content="OK"/></StackPanel>')}, Status.PASS),
        SelfTestCase("unbekannt: dynamisches Größenlimit", {"Dialog.xaml": _fixture(BODY, 'MaxHeight="{Binding Limit}"')}, Status.UNMEASURED),
        SelfTestCase("unbekannt: benutzerdefiniertes Control", {"Dialog.xaml": _fixture('<custom:Form xmlns:custom="clr-namespace:Example"/>')}, Status.UNMEASURED),
        SelfTestCase("unbekannt: Scrollen nur in Unterliste", {"Dialog.xaml": _fixture(BODY.replace('<TextBlock', '<ListBox/><TextBlock'))}, Status.UNMEASURED),
        SelfTestCase("unbekannt: anderes Framework", {"Dialog.xaml": '<Window xmlns="https://github.com/avaloniaui" SizeToContent="Height" MaxHeight="650"/>'}, Status.UNMEASURED),
        SelfTestCase("unbekannt: ungebundener Größenpfad", {"Dialog.xaml": _fixture(BODY, '')}, Status.UNMEASURED),
    ],
)
def check_dialog_scroll(ctx: Context) -> CheckResult:
    findings: list[Finding] = []
    units = 0
    unknown = []
    for sf in ctx.files(".xaml"):
        if NS[1:-1] not in sf.text:
            continue
        if "<!DOCTYPE" in sf.text or "<!ENTITY" in sf.text:
            unknown.append(sf.rel)
            continue
        try:
            root = ET.fromstring(sf.text)
        except ET.ParseError:
            unknown.append(sf.rel)
            continue
        if (not root.tag.rsplit("}", 1)[-1].endswith("Window")
                or root.get("SizeToContent") not in {"Height", "WidthAndHeight"}):
            continue
        limit = root.get("MaxHeight")
        if limit is not None:
            try:
                height = float(limit)
                if not math.isfinite(height) or height <= 0:
                    raise ValueError
            except ValueError:
                unknown.append(sf.rel)
                continue
        elif root.get("ResizeMode") != "NoResize":
            unknown.append(sf.rel)
            continue
        children = _children(root)
        state = _shape(children[0]) if len(children) == 1 else "unknown"
        if state == "unknown":
            unknown.append(sf.rel)
            continue
        units += 1
        if state == "unsafe" and _may_grow(children[0]):
            match = re.search(r"<(?:[\w.-]+:)?[\w.-]*Window\b", sf.text)
            line = sf.text.count("\n", 0, match.start()) + 1 if match else 1
            findings.append(Finding(
                CID, Severity.WARNING,
                "Höhenbegrenzter, inhaltshoch gemessener Dialog mit Auto-Inhalt ohne Scrollweg: "
                "lange Texte/Bilder können Aktionsbuttons abschneiden.",
                file=sf.rel, line=line, evidence="SizeToContent=" + root.get("SizeToContent", ""),
                fix="Inhalt in einen vertikalen ScrollViewer legen und dessen Viewport begrenzen; "
                    "Aktionsbuttons möglichst in einer separaten Auto-Zeile halten. "
                    "Kleine Höhe und große Textgröße unter Windows bedienen.",
            ))
    if not units:
        return unmeasured(CID, TITLE, "Kein eindeutig prüfbarer Dialog-Scrollpfad. "
                          + ", ".join(unknown[:5]), "dotnet")
    result = result_for(CID, TITLE, findings, units, "statische Dialog-Scrollpfade", "dotnet")
    result.reason = "Nur XAML-Struktur; keine Windows-Abnahme. Ungemessene Layouts: " + str(len(unknown))
    return result
