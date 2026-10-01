"""
WPF-/.NET-Desktop-Checks aus CODE_QUALITY_GUIDELINES_WPF.md und
CODE_QUALITY_GUIDELINES_DOTNET_UI.md.

Belegt in einem WPF-Desktopprojekt (.NET 9). Dort ist Linux kein Buildhost,
das Gate ist GitHub Actions auf Windows. Jeder Fehler, den erst der
Windows-Build oder gar erst der App-Start meldet, kostet einen CI-Lauf, und
bei leerem Minutenkontingent bleibt er ganz unbemerkt. Die Checks hier
fangen diese Fälle offline ab:

* § 3.1 ``new Thickness(a, b)``: CS1729, WPF kennt nur 1 oder 4 Argumente
* § 3.2 ``Style`` als Attribut UND als Property-Element: Markup-Buildfehler
* § 3.3 ``<Run Text="{Binding …}">`` ohne Mode: bindet TwoWay, Absturz beim
        Start bei schreibgeschützter Quelle
* § 3.4 ``CommandParameter="1"`` auf ``RelayCommand<int>``: WPF übergibt
        immer ``string``, CanExecute wirft ArgumentException
* ComboBox-Template ohne ``PART_EditableTextBox``: editierbare ComboBox zeigt
  bei geschlossenem Dropdown keinen Text
* § 0 Globale UI-Skalierung per LayoutTransform/ScaleTransform
* DOTNET_UI § 4 ``async void`` außerhalb von Event-Handlern
"""

from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, snippet, strip_comments,
)

PLATFORM = "dotnet"
GUIDE = "CODE_QUALITY_GUIDELINES_WPF.md"

WPF_XMLNS = "schemas.microsoft.com/winfx/2006/xaml/presentation"

_WPF_XAML_HEAD = (
    '<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"\n'
    '             xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">\n'
)
_WPF_XAML_TAIL = "</UserControl>\n"


def _wpf_xaml(ctx: Context):
    """(Datei, Text ohne Kommentare) aller WPF-XAML-Dateien.

    Erkannt am WPF-Namespace, nicht an der Endung: Avalonia- und MAUI-XAML
    haben andere Regeln (Avalonia kennt z. B. Thickness mit zwei Werten).
    """
    out = []
    for sf in ctx.files(".xaml"):
        if WPF_XMLNS in sf.text:
            out.append((sf, strip_comments(sf.text, sf.ext)))
    return out


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _raw_line(sf, line_no: int) -> str:
    lines = sf.lines
    return lines[line_no - 1] if 0 < line_no <= len(lines) else ""


# ---------------------------------------------------------------------------
# § 3.3 Run.Text
# ---------------------------------------------------------------------------

_RUN_TEXT_BINDING = re.compile(
    r"<Run\b[^>]*?\bText\s*=\s*\"\{Binding\b([^\"]*)\}\"", re.DOTALL)


@register(
    "dotnet.wpf_run_text_binding_without_mode",
    "Run.Text-Binding ohne Mode (bindet TwoWay)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=f"{GUIDE} § 3.3",
    rationale=(
        "Run.Text hat BindsTwoWayByDefault=true, anders als TextBlock.Text. "
        "Zeigt die Quelle auf eine schreibgeschützte Eigenschaft (z. B. "
        "ObservableCollection.Count), wirft WPF beim Laden "
        "InvalidOperationException: 'A TwoWay or OneWayToSource binding cannot "
        "work on the read-only property'. Ein Run ist nie editierbar, ein "
        "ausdrücklicher Mode ist daher immer richtig."
    ),
    self_tests=[
        SelfTestCase(
            name="Run ohne Mode",
            files={"Views/A.xaml": _WPF_XAML_HEAD
                   + '<TextBlock><Run Text="{Binding Items.Count}"/></TextBlock>\n'
                   + _WPF_XAML_TAIL},
            expect=Status.FAIL,
            expect_finding_contains="Items.Count",
        ),
        SelfTestCase(
            name="Run mit Mode=OneWay, TextBlock ohne Mode",
            files={"Views/A.xaml": _WPF_XAML_HEAD
                   + '<TextBlock><Run Text="{Binding Items.Count, Mode=OneWay}"/></TextBlock>\n'
                   + '<TextBlock Text="{Binding Name}"/>\n'
                   + _WPF_XAML_TAIL},
            expect=Status.PASS,
        ),
    ],
)
def check_run_text_mode(ctx: Context) -> CheckResult:
    cid = "dotnet.wpf_run_text_binding_without_mode"
    title = "Run.Text-Binding ohne Mode (bindet TwoWay)"
    findings: list[Finding] = []
    units = 0
    for sf, text in _wpf_xaml(ctx):
        for m in _RUN_TEXT_BINDING.finditer(text):
            units += 1
            if re.search(r"\bMode\s*=", m.group(1)):
                continue
            line = _line_of(text, m.start())
            findings.append(Finding(
                check_id=cid, severity=Severity.ERROR,
                message=f"<Run Text=\"{{Binding{m.group(1)}}}\"> ohne Mode bindet "
                        "TwoWay; bei schreibgeschützter Quelle stürzt die Ansicht beim Laden ab.",
                file=sf.rel, line=line, evidence=snippet(_raw_line(sf, line)),
                fix="Mode=OneWay ergänzen (Run ist nie editierbar).",
            ))
    return result_for(cid, title, findings, units, "Run-Bindings", PLATFORM)


# ---------------------------------------------------------------------------
# § 3.4 CommandParameter-Literal auf RelayCommand<Werttyp>
# ---------------------------------------------------------------------------

_VALUE_TYPES = r"(?:int|long|short|byte|double|float|decimal|bool|DateTime|Guid|TimeSpan)"
_RELAY_VALUE_CMD = re.compile(
    r"\[RelayCommand\b[^\]]*\]\s*(?:\[[^\]]*\]\s*)*"
    r"(?:(?:private|public|protected|internal|static|async|partial|virtual|override)\s+)*"
    r"(?:void|Task(?:<[^>]+>)?)\s+(\w+)\s*\(\s*(" + _VALUE_TYPES + r")\??\s+\w+"
    r"\s*(?:,\s*(?:System\.Threading\.)?CancellationToken\s+\w+\s*)?\)")
_XAML_TAG = re.compile(r"<[A-Za-z][\w:.]*\b[^>]*>", re.DOTALL)
_CMD_PARAM_LITERAL = re.compile(r"\bCommandParameter\s*=\s*\"([^\"{][^\"]*)\"")


def _generated_command_name(method: str) -> str:
    """Name der von CommunityToolkit.Mvvm erzeugten Eigenschaft."""
    name = method
    if name.startswith("On") and len(name) > 2 and name[2].isupper():
        name = name[2:]
    if name.endswith("Async") and len(name) > 5:
        name = name[:-5]
    return name + "Command"


@register(
    "dotnet.wpf_commandparameter_literal_to_value_type",
    "CommandParameter-Literal an RelayCommand mit Werttyp",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=f"{GUIDE} § 3.4",
    rationale=(
        "WPF übergibt ein CommandParameter-Attribut immer als string. "
        "RelayCommand<int> prüft den Typ in CanExecute und wirft "
        "ArgumentException (Parameter cannot be of type System.String). "
        "Der Fehler fällt erst beim Öffnen der Ansicht auf."
    ),
    self_tests=[
        SelfTestCase(
            name="int-Command mit Literal",
            files={
                "ViewModels/VM.cs": (
                    "public partial class VM {\n"
                    "    [RelayCommand]\n"
                    "    private void SelectQuarter(int quarter) { }\n"
                    "}\n"),
                "Views/V.xaml": _WPF_XAML_HEAD
                + '<Button Command="{Binding SelectQuarterCommand}" CommandParameter="1"/>\n'
                + _WPF_XAML_TAIL,
            },
            expect=Status.FAIL,
            expect_finding_contains="SelectQuarterCommand",
        ),
        SelfTestCase(
            name="string-Parameter bzw. sys:Int32-Element",
            files={
                "ViewModels/VM.cs": (
                    "public partial class VM {\n"
                    "    [RelayCommand]\n"
                    "    private void SelectQuarter(string quarterStr) { }\n"
                    "    [RelayCommand]\n"
                    "    private async Task PickYearAsync(int year) { }\n"
                    "}\n"),
                "Views/V.xaml": _WPF_XAML_HEAD
                + '<Button Command="{Binding SelectQuarterCommand}" CommandParameter="1"/>\n'
                + '<Button Command="{Binding PickYearCommand}">\n'
                + '  <Button.CommandParameter><sys:Int32>2026</sys:Int32></Button.CommandParameter>\n'
                + '</Button>\n'
                + _WPF_XAML_TAIL,
            },
            expect=Status.PASS,
        ),
    ],
)
def check_commandparameter_value_type(ctx: Context) -> CheckResult:
    cid = "dotnet.wpf_commandparameter_literal_to_value_type"
    title = "CommandParameter-Literal an RelayCommand mit Werttyp"
    commands: dict[str, str] = {}
    for sf in ctx.files(".cs"):
        if "RelayCommand" not in sf.text:
            continue
        text = strip_comments(sf.text, sf.ext)
        for m in _RELAY_VALUE_CMD.finditer(text):
            commands[_generated_command_name(m.group(1))] = m.group(2)
    findings: list[Finding] = []
    if commands:
        cmd_ref = re.compile(
            r"\bCommand\s*=\s*\"\{Binding\s+(?:Path\s*=\s*)?(?:[\w.]+\.)?("
            + "|".join(map(re.escape, commands)) + r")\b")
        for sf, text in _wpf_xaml(ctx):
            for tag in _XAML_TAG.finditer(text):
                ref = cmd_ref.search(tag.group(0))
                lit = _CMD_PARAM_LITERAL.search(tag.group(0)) if ref else None
                if not lit:
                    continue
                line = _line_of(text, tag.start())
                findings.append(Finding(
                    check_id=cid, severity=Severity.ERROR,
                    message=f"{ref.group(1)} erwartet {commands[ref.group(1)]}, "
                            f"CommandParameter=\"{lit.group(1)}\" kommt als string an.",
                    file=sf.rel, line=line, evidence=snippet(_raw_line(sf, line)),
                    fix="Parameter als string annehmen und intern parsen, oder im XAML "
                        "ein typisiertes Element übergeben (<sys:Int32>1</sys:Int32>).",
                ))
    return result_for(cid, title, findings, len(commands),
                      "RelayCommands mit Werttyp", PLATFORM)


# ---------------------------------------------------------------------------
# § 3.2 Style doppelt gesetzt
# ---------------------------------------------------------------------------

_OPEN_WITH_STYLE = re.compile(
    r"<([A-Za-z][\w:]*)\b(?=[^>]*?\sStyle\s*=)[^>]*?(/?)>", re.DOTALL)


def _style_property_element_inside(text: str, name: str, start: int) -> int | None:
    """Position von <Name.Style> als direktes Property-Element, sonst None."""
    esc = re.escape(name)
    token = re.compile(
        rf"<{esc}\.Style\b|</{esc}\s*>|<{esc}(?![\w:.])[^>]*?(/?)>", re.DOTALL)
    depth = 1
    for t in token.finditer(text, start):
        s = t.group(0)
        if s.startswith(f"<{name}.Style"):
            if depth == 1:
                return t.start()
        elif s.startswith("</"):
            depth -= 1
            if depth == 0:
                return None
        elif not t.group(1):
            depth += 1
    return None


@register(
    "dotnet.wpf_style_set_twice",
    "Style als Attribut und als Property-Element gesetzt",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=f"{GUIDE} § 3.2",
    rationale=(
        "Eine Eigenschaft darf in XAML nur einmal gesetzt werden. "
        "Style=\"{StaticResource …}\" plus <Button.Style> bricht den "
        "Markup-Build ('The property Style is set more than once'); auf einem "
        "Linux-Host ohne Windows-Build fällt das erst in CI auf."
    ),
    self_tests=[
        SelfTestCase(
            name="Attribut plus Property-Element",
            files={"Views/A.xaml": _WPF_XAML_HEAD
                   + '<Button Style="{StaticResource Foo}">\n'
                   + '  <Button.Style><Style TargetType="Button"/></Button.Style>\n'
                   + '</Button>\n' + _WPF_XAML_TAIL},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="nur eins von beiden, verschachtelter Button mit eigenem Style",
            files={"Views/A.xaml": _WPF_XAML_HEAD
                   + '<Button Style="{StaticResource Foo}">\n'
                   + '  <Button Content="x">\n'
                   + '    <Button.Style><Style BasedOn="{StaticResource Foo}"/></Button.Style>\n'
                   + '  </Button>\n'
                   + '</Button>\n'
                   + '<Button Style="{StaticResource Foo}"/>\n'
                   + _WPF_XAML_TAIL},
            expect=Status.PASS,
        ),
    ],
)
def check_style_twice(ctx: Context) -> CheckResult:
    cid = "dotnet.wpf_style_set_twice"
    title = "Style als Attribut und als Property-Element gesetzt"
    findings: list[Finding] = []
    units = 0
    for sf, text in _wpf_xaml(ctx):
        for m in _OPEN_WITH_STYLE.finditer(text):
            units += 1
            if m.group(2):  # selbstschließend: kein Property-Element möglich
                continue
            pos = _style_property_element_inside(text, m.group(1), m.end())
            if pos is None:
                continue
            line = _line_of(text, m.start())
            findings.append(Finding(
                check_id=cid, severity=Severity.ERROR,
                message=f"<{m.group(1)}> setzt Style als Attribut und nochmal als "
                        f"<{m.group(1)}.Style> (Zeile {_line_of(text, pos)}).",
                file=sf.rel, line=line, evidence=snippet(_raw_line(sf, line)),
                fix="Nur eines behalten: das Attribut entfernen und im Property-Element "
                    "<Style BasedOn=\"{StaticResource …}\"> verwenden.",
            ))
    return result_for(cid, title, findings, units, "Elemente mit Style", PLATFORM)


# ---------------------------------------------------------------------------
# § 3.1 Thickness mit zwei Argumenten
# ---------------------------------------------------------------------------

_NEW_THICKNESS = re.compile(r"\bnew\s+(?:System\.Windows\.)?Thickness\s*\(")


def _top_level_args(text: str, open_pos: int) -> int | None:
    """Anzahl der Argumente ab der öffnenden Klammer, None bei offenem Ende."""
    depth = 0
    commas = 0
    empty = True
    for i in range(open_pos, len(text)):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return 0 if empty else commas + 1
        elif depth == 1:
            if ch == ",":
                commas += 1
            elif not ch.isspace():
                empty = False
    return None


@register(
    "dotnet.wpf_thickness_two_args",
    "new Thickness(a, b) — WPF kennt nur 1 oder 4 Argumente",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=f"{GUIDE} § 3.1",
    rationale=(
        "System.Windows.Thickness hat Konstruktoren mit 1 und 4 Argumenten. "
        "Zwei Argumente sind CS1729 ('Thickness' does not contain a constructor "
        "that takes 2 arguments). Avalonia und MAUI kennen die Zwei-Werte-Form, "
        "deshalb zählen nur Dateien mit System.Windows und ohne Avalonia/MAUI."
    ),
    self_tests=[
        SelfTestCase(
            name="WPF mit zwei Argumenten",
            files={"Views/A.cs": ("using System.Windows;\n"
                                  "class A { object M() => new Thickness(0, 10); }\n")},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="WPF mit 1/4 Argumenten, Avalonia mit 2",
            files={
                "Views/A.cs": ("using System.Windows;\n"
                               "class A { object M() => new Thickness(Math.Max(0, 1), 10, 0, 10);\n"
                               "  object N() => new Thickness(4); }\n"),
                "Views/B.cs": ("using Avalonia;\n"
                               "class B { object M() => new Thickness(0, 10); }\n"),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_thickness_args(ctx: Context) -> CheckResult:
    cid = "dotnet.wpf_thickness_two_args"
    title = "new Thickness(a, b) — WPF kennt nur 1 oder 4 Argumente"
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(".cs"):
        if "Thickness" not in sf.text:
            continue
        text = strip_comments(sf.text, sf.ext)
        if not re.search(r"\busing\s+System\.Windows\b|System\.Windows\.Thickness", text):
            continue
        if re.search(r"\busing\s+(?:Avalonia|Microsoft\.Maui)\b", text):
            continue
        for m in _NEW_THICKNESS.finditer(text):
            units += 1
            if _top_level_args(text, m.end() - 1) != 2:
                continue
            line = _line_of(text, m.start())
            findings.append(Finding(
                check_id=cid, severity=Severity.ERROR,
                message="new Thickness mit zwei Argumenten baut in WPF nicht (CS1729).",
                file=sf.rel, line=line, evidence=snippet(_raw_line(sf, line)),
                fix="Vier Argumente angeben: new Thickness(links, oben, rechts, unten).",
            ))
    return result_for(cid, title, findings, units, "Thickness-Konstruktoren", PLATFORM)


# ---------------------------------------------------------------------------
# ComboBox-Template ohne PART_EditableTextBox
# ---------------------------------------------------------------------------

_COMBO_TEMPLATE = re.compile(
    r"<ControlTemplate\b[^>]*\bTargetType\s*=\s*\"(?:\{x:Type\s+)?ComboBox\}?\"[^>]*>"
    r"(.*?)</ControlTemplate>", re.DOTALL)
_EDITABLE_COMBO = re.compile(
    r"<ComboBox\b[^>]*\bIsEditable\s*=\s*\"(?:True|true|\{)", re.DOTALL)


@register(
    "dotnet.wpf_combobox_template_without_editable_part",
    "ComboBox-Template ohne PART_EditableTextBox bei editierbaren ComboBoxen",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline=f"{GUIDE} § 3 (ComboBox-Template)",
    rationale=(
        "Eine editierbare WPF-ComboBox schreibt ihren Text in das Template-Teil "
        "PART_EditableTextBox. Fehlt es im eigenen Template, bleibt der gewählte "
        "oder getippte Text bei geschlossenem Dropdown unsichtbar, ohne Fehler "
        "und ohne Log. Hinweis statt Fehler, weil eine editierbare ComboBox "
        "auch ein eigenes Template tragen kann."
    ),
    self_tests=[
        SelfTestCase(
            name="Template ohne Part, editierbare ComboBox im Projekt",
            files={
                "Styles/S.xaml": _WPF_XAML_HEAD
                + '<ControlTemplate TargetType="ComboBox"><ContentPresenter x:Name="ContentSite"/></ControlTemplate>\n'
                + _WPF_XAML_TAIL,
                "Views/V.xaml": _WPF_XAML_HEAD + '<ComboBox IsEditable="True"/>\n' + _WPF_XAML_TAIL,
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Template mit Part bzw. keine editierbare ComboBox",
            files={
                "Styles/S.xaml": _WPF_XAML_HEAD
                + '<ControlTemplate TargetType="{x:Type ComboBox}"><Grid>'
                + '<ContentPresenter x:Name="ContentSite"/><TextBox x:Name="PART_EditableTextBox"/>'
                + '</Grid></ControlTemplate>\n' + _WPF_XAML_TAIL,
                "Views/V.xaml": _WPF_XAML_HEAD + '<ComboBox IsEditable="True"/>\n' + _WPF_XAML_TAIL,
            },
            expect=Status.PASS,
        ),
    ],
)
def check_combobox_template(ctx: Context) -> CheckResult:
    cid = "dotnet.wpf_combobox_template_without_editable_part"
    title = "ComboBox-Template ohne PART_EditableTextBox bei editierbaren ComboBoxen"
    xaml = _wpf_xaml(ctx)
    editable = any(_EDITABLE_COMBO.search(text) for _, text in xaml)
    findings: list[Finding] = []
    units = 0
    for sf, text in xaml:
        for m in _COMBO_TEMPLATE.finditer(text):
            units += 1
            if not editable or "PART_EditableTextBox" in m.group(1):
                continue
            line = _line_of(text, m.start())
            findings.append(Finding(
                check_id=cid, severity=Severity.WARNING,
                message="Eigenes ComboBox-Template ohne PART_EditableTextBox, aber das "
                        "Projekt nutzt IsEditable=\"True\": der Text bleibt dort unsichtbar.",
                file=sf.rel, line=line, evidence=snippet(_raw_line(sf, line)),
                fix="<TextBox x:Name=\"PART_EditableTextBox\" Visibility=\"Collapsed\"/> ins "
                    "Template, per Trigger auf IsEditable=True sichtbar schalten.",
            ))
    return result_for(cid, title, findings, units, "ComboBox-Templates", PLATFORM)


# ---------------------------------------------------------------------------
# § 0 Globale UI-Skalierung per LayoutTransform
# ---------------------------------------------------------------------------

_LAYOUT_TRANSFORM = re.compile(r"<[\w:]+\.LayoutTransform\s*>(.*?)</[\w:]+\.LayoutTransform\s*>",
                               re.DOTALL)
_DYNAMIC_SCALE = re.compile(
    r"<ScaleTransform\b[^>]*\bScale[XY]\s*=\s*\"\{(?:Binding|DynamicResource|StaticResource)\b",
    re.DOTALL)


@register(
    "dotnet.wpf_layouttransform_ui_scaling",
    "UI-Skalierung per LayoutTransform/ScaleTransform",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline=f"{GUIDE} § 0",
    rationale=(
        "Eine gebundene ScaleTransform im LayoutTransform skaliert Pixel statt "
        "Schrift: Text wird unscharf, Layout-Messungen stimmen nicht mehr, "
        "Scrollbereiche und Popups laufen aus dem Fenster. Skalierung gehört "
        "in DynamicResource-Schriftgrößen."
    ),
    self_tests=[
        SelfTestCase(
            name="gebundene Skalierung",
            files={"Views/A.xaml": _WPF_XAML_HEAD
                   + '<Grid><Grid.LayoutTransform>\n'
                   + '  <ScaleTransform ScaleX="{Binding UiScale}" ScaleY="{Binding UiScale}"/>\n'
                   + '</Grid.LayoutTransform></Grid>\n' + _WPF_XAML_TAIL},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="feste Drehung/Spiegelung eines Symbols",
            files={"Views/A.xaml": _WPF_XAML_HEAD
                   + '<Path><Path.LayoutTransform><ScaleTransform ScaleX="-1"/></Path.LayoutTransform></Path>\n'
                   + _WPF_XAML_TAIL},
            expect=Status.PASS,
        ),
    ],
)
def check_layouttransform_scaling(ctx: Context) -> CheckResult:
    cid = "dotnet.wpf_layouttransform_ui_scaling"
    title = "UI-Skalierung per LayoutTransform/ScaleTransform"
    findings: list[Finding] = []
    units = 0
    for sf, text in _wpf_xaml(ctx):
        for m in _LAYOUT_TRANSFORM.finditer(text):
            units += 1
            if not _DYNAMIC_SCALE.search(m.group(1)):
                continue
            line = _line_of(text, m.start())
            findings.append(Finding(
                check_id=cid, severity=Severity.WARNING,
                message="LayoutTransform mit gebundener ScaleTransform: skaliert Pixel statt Schrift.",
                file=sf.rel, line=line, evidence=snippet(_raw_line(sf, line)),
                fix="Schriftgrößen als DynamicResource-Schlüssel führen und zentral umrechnen.",
            ))
    return result_for(cid, title, findings, units, "LayoutTransforms", PLATFORM)


# ---------------------------------------------------------------------------
# DOTNET_UI § 4 async void
# ---------------------------------------------------------------------------

_ASYNC_VOID = re.compile(r"\basync\s+void\s+(\w+)\s*\(([^)]*)\)")


@register(
    "dotnet.async_void_outside_event_handler",
    "async void außerhalb eines Event-Handlers",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_DOTNET_UI.md § 4",
    rationale=(
        "Eine Ausnahme aus einer async-void-Methode lässt sich nicht abfangen "
        "und beendet den Prozess über den Dispatcher; Aufrufer können nicht "
        "warten. Zulässig nur für Event-Handler (Parameter vom Typ *EventArgs)."
    ),
    self_tests=[
        SelfTestCase(
            name="async void mit Nutzdaten-Parameter",
            files={"A.cs": "class A { private async void Load(string path) { await Task.Delay(1); } }\n"},
            expect=Status.FAIL,
            expect_finding_contains="Load",
        ),
        SelfTestCase(
            name="Event-Handler und override",
            files={"A.cs": (
                "class A {\n"
                "  private async void OnClick(object sender, RoutedEventArgs e) { await Task.Delay(1); }\n"
                "  protected override async void OnStartup(StartupEventArgs e) { await Task.Delay(1); }\n"
                "  private async Task LoadAsync() { await Task.Delay(1); }\n"
                "}\n")},
            expect=Status.PASS,
        ),
    ],
)
def check_async_void(ctx: Context) -> CheckResult:
    cid = "dotnet.async_void_outside_event_handler"
    title = "async void außerhalb eines Event-Handlers"
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(".cs"):
        if "async" not in sf.text:
            continue
        text = strip_comments(sf.text, sf.ext)
        for m in _ASYNC_VOID.finditer(text):
            units += 1
            if re.search(r"\w*EventArgs\b", m.group(2)):
                continue
            line = _line_of(text, m.start())
            findings.append(Finding(
                check_id=cid, severity=Severity.WARNING,
                message=f"async void {m.group(1)}(…) ist kein Event-Handler: Ausnahmen "
                        "beenden den Prozess, Aufrufer können nicht warten.",
                file=sf.rel, line=line, evidence=snippet(_raw_line(sf, line)),
                fix="async Task zurückgeben (bei [RelayCommand] erzeugt das Toolkit "
                    "dann einen AsyncRelayCommand).",
            ))
    return result_for(cid, title, findings, units, "async-void-Methoden", PLATFORM)


# ---------------------------------------------------------------------------
# Grundsatz A/C (eine Quelle): Datenpfade
# ---------------------------------------------------------------------------

_DATA_FOLDER_CALL = re.compile(
    r"GetFolderPath\s*\(\s*(?:System\s*\.\s*)?(?:Environment\s*\.\s*)?SpecialFolder\s*\.\s*"
    r"(ApplicationData|LocalApplicationData|CommonApplicationData)\b")

@register(
    "dotnet.data_path_single_source",
    "Datenordner wird an mehreren Stellen zusammengesetzt",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_DOTNET_UI.md § Datenpfade",
    rationale=(
        "Wo Datenbank, Einstellungen, Logs und Backups ihren Ordner je selbst aus "
        "%APPDATA% bauen, ist ein Umzug des Datenorts (z. B. fester Installationsordner "
        "für die IT) eine Suche über die ganze Codebasis — eine vergessene Stelle "
        "schreibt still weiter an den alten Ort. Belegt in einem Desktopprojekt: "
        "11 Aufrufe in 9 Dateien. Eine Pfadklasse, alle anderen fragen sie."
    ),
    self_tests=[
        SelfTestCase(
            name="Datenordner in zwei Dateien gebaut",
            files={
                "Db.cs": "class Db { string p = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), \"X\"); }\n",
                "Log.cs": "class Log { string p = System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData); }\n",
            },
            expect=Status.FAIL,
            expect_finding_contains="Log.cs",
        ),
        SelfTestCase(
            name="eine Pfadklasse, Dokumente-Ordner anderswo",
            files={
                "AppPaths.cs": (
                    "static class AppPaths {\n"
                    "  static string A = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);\n"
                    "  static string B = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);\n"
                    "}\n"),
                "Dialog.cs": "class D { string p = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments); }\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_data_path_single_source(ctx: Context) -> CheckResult:
    cid = "dotnet.data_path_single_source"
    title = "Datenordner wird an mehreren Stellen zusammengesetzt"
    sites: list[tuple] = []
    for sf in ctx.files(".cs"):
        if "SpecialFolder" not in sf.text:
            continue
        text = strip_comments(sf.text, sf.ext)
        for m in _DATA_FOLDER_CALL.finditer(text):
            sites.append((sf, _line_of(text, m.start()), m.group(1)))
    files = sorted({sf.rel for sf, _, _ in sites})
    findings: list[Finding] = []
    if len(files) > 1:
        for sf, line, folder in sites:
            findings.append(Finding(
                check_id=cid, severity=Severity.WARNING,
                message=f"SpecialFolder.{folder} wird in {len(files)} Dateien aufgelöst "
                        f"({', '.join(files[:4])}{' …' if len(files) > 4 else ''}): "
                        "der Datenort hat keine eine Quelle.",
                file=sf.rel, line=line, evidence=snippet(_raw_line(sf, line)),
                fix="Eine statische Pfadklasse (z. B. AppPaths) liefert DataRoot, "
                    "DatabasePath, LogsPath …; alle anderen Stellen fragen nur sie.",
            ))
    return result_for(cid, title, findings, len(sites), "Datenordner-Aufrufe", PLATFORM)


# ---------------------------------------------------------------------------
# Path.GetTempFileName() + Endung: die angelegte .tmp-Datei bleibt liegen
# ---------------------------------------------------------------------------

_TEMP_FILE_NAME_SUFFIX = re.compile(r"Path\s*\.\s*GetTempFileName\s*\(\s*\)\s*\+")
_TEMP_FILE_NAME_ANY = re.compile(r"Path\s*\.\s*GetTempFileName\s*\(\s*\)")

@register(
    "dotnet.temp_file_name_with_suffix",
    "GetTempFileName() + Endung lässt eine leere .tmp-Datei zurück",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_DOTNET_UI.md § Datenpfade",
    references=("https://learn.microsoft.com/en-us/dotnet/api/system.io.path.gettempfilename",),
    rationale=(
        "Path.GetTempFileName() legt die Datei sofort an. Wer eine Endung anhängt, "
        "schreibt in eine ZWEITE Datei und löscht nur diese — die leere .tmp-Datei "
        "bleibt bei jedem Aufruf liegen. Belegt in einem Desktopprojekt (ICS-Export)."
    ),
    self_tests=[
        SelfTestCase(
            name="Endung an GetTempFileName angehängt",
            files={"Ics.cs": "class I { string p = Path.GetTempFileName() + \".ics\"; }\n"},
            expect=Status.FAIL,
            expect_finding_contains="GetTempFileName",
        ),
        SelfTestCase(
            name="GetTempFileName direkt benutzt, eigener Name im Arbeitsordner",
            files={"Ics.cs": (
                "class I {\n"
                "  string a = Path.GetTempFileName();\n"
                "  string b = Path.Combine(dir, $\"ics_{Guid.NewGuid():N}.ics\");\n"
                "}\n")},
            expect=Status.PASS,
        ),
    ],
)
def check_temp_file_name_with_suffix(ctx: Context) -> CheckResult:
    cid = "dotnet.temp_file_name_with_suffix"
    title = "GetTempFileName() + Endung lässt eine leere .tmp-Datei zurück"
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(".cs"):
        if "GetTempFileName" not in sf.text:
            continue
        text = strip_comments(sf.text, sf.ext)
        units += len(_TEMP_FILE_NAME_ANY.findall(text))
        for m in _TEMP_FILE_NAME_SUFFIX.finditer(text):
            line = _line_of(text, m.start())
            findings.append(Finding(
                check_id=cid, severity=Severity.WARNING,
                message="Path.GetTempFileName() legt die Datei an; mit angehängter Endung "
                        "bleibt sie ungelöscht liegen.",
                file=sf.rel, line=line, evidence=snippet(_raw_line(sf, line)),
                fix="Eigenen Namen bauen (Path.Combine(ordner, $\"x_{Guid.NewGuid():N}.ics\")) "
                    "oder die von GetTempFileName gelieferte Datei selbst benutzen und löschen.",
            ))
    return result_for(cid, title, findings, units, "GetTempFileName-Aufrufe", PLATFORM)
