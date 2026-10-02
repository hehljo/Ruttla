"""
Einstellung ohne Verbraucher: ein Feld, das der Benutzer bearbeitet, das aber
außerhalb seines Editors niemand liest.

Laden → anzeigen → speichern ist ein Kreis, der nur den eigenen Editor berührt.
Belegt in einem WPF-Desktopprojekt: eine Profil-Auswahl wurde monatelang
gespeichert, angezeigt und kopiert, gelesen hat sie niemand — die Berechnung
lief fest mit dem Standardwert. Alle Lesestellen standen in derselben Klasse,
die das Feld auch schrieb.

Eine grobe Probe „Leser ⊆ Schreiber“ über alle Modellfelder meldet fast nur
Falsches (Felder, die legitim nur ein Dienst liest und schreibt). Deshalb
prüft der Check nur, was der Benutzer bearbeitet:

* Kandidat: ein ViewModel lädt ``x.Feld`` in eine eigene Eigenschaft, die im
  XAML gebunden ist, und schreibt sie von dort nach ``x.Feld`` zurück. Das
  Feld ist als ``{ get; set; }`` außerhalb dieses ViewModels deklariert.
* Befund: außerhalb dieses ViewModels, der Deklarationsdatei und der Tests
  liest niemand ``.Feld`` (auch verkettet ``a.b.Feld`` und ``?.Feld``).
  Zuweisungsziel und reine Kopie ``a.Feld = b.Feld`` sind kein Lesen.
* Null Kandidaten = nicht gemessen.
"""

from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, snippet, strip_comments,
)

PLATFORM = "dotnet"
CID = "dotnet.config_field_without_consumer"
TITLE = "Bearbeitetes Feld ohne Verbraucher außerhalb des Editors"

_IDENT = r"@?[A-Za-z_]\w*"
_ASSIGN = r"=(?![=>])"
# Zuweisung an einen bloßen Namen (VM-Eigenschaft oder Feld, kein x.Name).
_PLAIN_ASSIGN = re.compile(r"(?<![\w.?@])(" + _IDENT + r")\s*" + _ASSIGN + r"\s*([^;{}]*)")
# Mitglied-Zugriff im Ausdruck, kein Methodenaufruf.
_MEMBER = re.compile(r"\??\.\s*(" + _IDENT + r")\b(?!\s*[(<])")
_NAMEOF = re.compile(r"\bnameof\s*\([^()]*\)")
_BINDING = re.compile(r"\{(?:Binding|CompiledBinding)\b[^{}]*\}")
_TYPE_HEAD = re.compile(r"\b(?:class|record|struct)\s+(" + _IDENT + r")")
# [ObservableProperty] private string _foo; — der Feldname vor ; oder =.
_OBSERVABLE_FIELD = re.compile(r"\[ObservableProperty[^\]]*\][^;=]*?(" + _IDENT + r")\s*[;=]")
_TEST_ATTR = re.compile(r"\[\s*(?:Fact|Theory|Test|TestMethod|TestCase)\b")


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _raw_line(sf, line_no: int) -> str:
    lines = sf.lines
    return lines[line_no - 1] if 0 < line_no <= len(lines) else ""


def _generated_name(name: str) -> str:
    """[ObservableProperty] _foo / m_foo / foo → Foo."""
    n = name.lstrip("@")
    if n.startswith("m_"):
        n = n[2:]
    n = n.lstrip("_")
    return n[:1].upper() + n[1:] if n else name


def _cs_text(sf) -> str:
    return _NAMEOF.sub(lambda m: " " * len(m.group(0)), strip_comments(sf.text, sf.ext))


def _bound_names(ctx: Context) -> set[str]:
    names: set[str] = set()
    for sf in ctx.files(".xaml", ".axaml"):
        for m in _BINDING.finditer(strip_comments(sf.text, sf.ext)):
            names.update(re.findall(r"[A-Za-z_]\w*", m.group(0)))
    return names


def _declarations(files: list[tuple]) -> dict[str, list[tuple]]:
    """Feldname → [(Datei, Typname, Zeile)] aller { get; set; }-Eigenschaften."""
    decl = re.compile(
        r"\bpublic\s+(?:virtual\s+|override\s+|required\s+)*[\w<>\[\]?,.\s]+?\s+("
        + _IDENT + r")\s*\{\s*get\s*;\s*set\s*;")
    out: dict[str, list[tuple]] = {}
    for sf, text in files:
        heads = [(m.start(), m.group(1)) for m in _TYPE_HEAD.finditer(text)]
        for m in decl.finditer(text):
            owner = next((n for p, n in reversed(heads) if p < m.start()), "?")
            out.setdefault(m.group(1).lstrip("@"), []).append(
                (sf, owner, _line_of(text, m.start())))
    return out


def _is_bound_member(text: str, prop: str, bound: set[str]) -> bool:
    """Eigene, im XAML gebundene Eigenschaft — kein lokaler Zwischenwert."""
    p = re.escape(prop)
    if prop in bound and re.search(r"\b" + p + r"\s*(?:\{|=>)", text):
        return True
    gen = _generated_name(prop)
    return gen in bound and any(
        _generated_name(f) == gen for f in _OBSERVABLE_FIELD.findall(text))


def _edited_fields(text: str, bound: set[str]) -> dict[str, tuple[str, int]]:
    """Feld → (gebundene VM-Eigenschaft, Position des Ladens) für ein ViewModel."""
    loads: dict[str, list[tuple[str, int]]] = {}
    for m in _PLAIN_ASSIGN.finditer(text):
        prop = m.group(1).lstrip("@")
        if not _is_bound_member(text, prop, bound):
            continue
        for f in _MEMBER.finditer(m.group(2)):
            loads.setdefault(f.group(1).lstrip("@"), []).append((prop, m.start()))
    out: dict[str, tuple[str, int]] = {}
    for field, props in loads.items():
        back = re.compile(
            r"(?:\.\s*|[{,]\s*)" + re.escape(field) + r"\s*" + _ASSIGN + r"\s*([^;{},]*)")
        for m in back.finditer(text):
            for prop, pos in props:
                names = {prop, _generated_name(prop)}
                if any(re.search(r"(?<![\w.])" + re.escape(n) + r"\b", m.group(1))
                       for n in names):
                    out.setdefault(field, (prop, pos))
    return out


def _is_consuming_read(text: str, pos: int, end: int, field: str) -> bool:
    """Ein Zugriff ``.Feld`` an pos..end: Lesen, und keine bloße Kopie?"""
    if re.match(r"\s*" + _ASSIGN, text[end:]):
        return False  # Zuweisungsziel
    start = max(text.rfind(c, 0, pos) for c in ";{},")
    prefix = text[start + 1:pos]
    copy = re.search(r"(?<![\w@])" + re.escape(field) + r"\s*" + _ASSIGN
                     + r"\s*[\w.?@\s]*$", prefix)
    return not copy


_STRING = re.compile(r'(?<![$@])"(?:[^"\\\n]|\\.)*"')


def _reads_own_field(text: str, field: str) -> bool:
    """Liest die deklarierende Klasse ihr Feld selbst (berechnete Eigenschaft)?

    Bloßer Name ohne Punkt; Deklaration, Zuweisungsziel und Kopie zählen nicht.
    """
    text = _STRING.sub(lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', text)
    bare = re.compile(r"(?<![\w.@])(?:this\s*\.\s*)?" + re.escape(field) + r"\b(?!\s*[(<\w])")
    for m in bare.finditer(text):
        if re.match(r"\s*\{\s*get\b", text[m.end():]):
            continue  # Deklaration
        if _is_consuming_read(text, m.start(), m.end(), field):
            return True
    return False


@register(
    CID,
    TITLE,
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Existenz ist nicht Wirkung",
    rationale=(
        "Ein Feld, das der Benutzer im Editor bearbeitet, wird gespeichert und "
        "wieder angezeigt — Wirkung hat es erst, wenn ein Verbraucher außerhalb "
        "des Editors damit rechnet. Belegt in einem WPF-Desktopprojekt: eine "
        "Profil-Auswahl wurde monatelang gespeichert, gelesen hat sie niemand; die "
        "Berechnung lief fest mit dem Standardwert."
    ),
    self_tests=[
        SelfTestCase(
            name="Feld nur im eigenen Editor gelesen, anderswo nur kopiert",
            files={
                "Models/Lager.cs": (
                    "public class Lager {\n"
                    "    public Lager() { Farbe = \"rot\"; }\n"
                    "    [JsonPropertyName(\"Farbe\")]\n"
                    "    public string Name { get; set; } = \"\";\n"
                    "    public string Farbe { get; set; } = \"\";\n"
                    "    public Lager Clone() => new Lager { Name = Name, Farbe = this.Farbe };\n"
                    "}\n"),
                "ViewModels/LagerViewModel.cs": (
                    "public partial class LagerViewModel {\n"
                    "    [ObservableProperty] private string _gewaehlteFarbe = \"\";\n"
                    "    [ObservableProperty] private string _lagerName = \"\";\n"
                    "    void Laden(Lager? l) {\n"
                    "        GewaehlteFarbe = l?.Farbe ?? string.Empty;\n"
                    "        LagerName = l?.Name ?? string.Empty;\n"
                    "    }\n"
                    "    void Speichern(Lager l) {\n"
                    "        l.Farbe = GewaehlteFarbe ?? string.Empty;\n"
                    "        l.Name = LagerName;\n"
                    "    }\n"
                    "}\n"),
                "Services/Export.cs": (
                    "class Export {\n"
                    "    Lager Kopie(Lager a) => new Lager { Name = a.Name, Farbe = a.Farbe };\n"
                    "    string Titel(Lager a) => a.Name.ToUpper();\n"
                    "    void Zuruecksetzen(Lager a) { a.Farbe = \"\"; }\n"
                    "}\n"),
                "Tests/LagerTests.cs": (
                    "public class LagerTests {\n"
                    "    [Fact] public void F() { Assert.Equal(\"\", new Lager().Farbe); }\n"
                    "}\n"),
                "Views/LagerView.xaml": (
                    "<UserControl>\n"
                    "  <TextBox Text=\"{Binding LagerName}\"/>\n"
                    "  <ComboBox SelectedValue=\"{Binding GewaehlteFarbe, Mode=TwoWay}\"/>\n"
                    "</UserControl>\n"),
            },
            expect=Status.FAIL,
            expect_finding_contains="Lager.Farbe",
        ),
        SelfTestCase(
            name="Feld verkettet und mit ?. außerhalb gelesen",
            files={
                "Models/Lager.cs": (
                    "public class Lager {\n"
                    "    public string Farbe { get; set; } = \"\";\n"
                    "    public int Tiefe { get; set; }\n"
                    "    public int Fach { get; set; }\n"
                    "    public string Ort => $\"Fach {Fach}\";\n"
                    "}\n"),
                "ViewModels/LagerViewModel.cs": (
                    "public partial class LagerViewModel {\n"
                    "    public string GewaehlteFarbe { get; set; } = \"\";\n"
                    "    public int Tiefe { get; set; }\n"
                    "    public int Fach { get; set; }\n"
                    "    void Laden(Lager l) { GewaehlteFarbe = l.Farbe; Tiefe = l.Tiefe; Fach = l.Fach; }\n"
                    "    void Speichern(Lager l) { l.Farbe = GewaehlteFarbe; l.Tiefe = Tiefe; l.Fach = Fach; }\n"
                    "}\n"),
                "Services/Plan.cs": (
                    "class Plan {\n"
                    "    string F(Halle h) => h.Lager?.Farbe ?? \"grau\";\n"
                    "    int T(Halle h) => h.Bereich.Lager.Tiefe * 2;\n"
                    "}\n"),
                "Views/LagerView.xaml": (
                    "<UserControl>\n"
                    "  <ComboBox SelectedValue=\"{Binding GewaehlteFarbe}\"/>\n"
                    "  <TextBox Text=\"{Binding Path=Tiefe}\"/>\n"
                    "  <TextBox Text=\"{Binding Fach}\"/>\n"
                    "</UserControl>\n"),
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="nur ungebundene Zwischenwerte: nichts zu prüfen",
            files={
                "Models/Lager.cs": "public class Lager { public string Farbe { get; set; } = \"\"; }\n",
                "Services/Sync.cs": (
                    "class Sync {\n"
                    "    void S(Lager a, Lager b) { var f = a.Farbe; b.Farbe = f; }\n"
                    "}\n"),
                "Views/V.xaml": "<UserControl><TextBlock Text=\"{Binding Titel}\"/></UserControl>\n",
            },
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_config_field_without_consumer(ctx: Context) -> CheckResult:
    bound = _bound_names(ctx)
    cs = [(sf, _cs_text(sf)) for sf in ctx.files(".cs")]
    decls = _declarations(cs)
    tests = {sf.rel for sf, text in cs if _TEST_ATTR.search(text)}
    findings: list[Finding] = []
    units = 0
    for vm, vm_text in cs:
        if vm.rel in tests or not bound:
            continue
        for field, (prop, pos) in sorted(_edited_fields(vm_text, bound).items()):
            owners = [d for d in decls.get(field, []) if d[0].rel != vm.rel]
            if not owners:
                continue  # Feld des ViewModels selbst, kein Modellfeld
            units += 1
            skip = {vm.rel} | {d[0].rel for d in owners} | tests
            access = re.compile(r"\??\.\s*" + re.escape(field) + r"\b(?!\s*[(<\w])")
            if any(_is_consuming_read(text, m.start(), m.end(), field)
                   for sf, text in cs if sf.rel not in skip
                   for m in access.finditer(text)):
                continue
            if any(_reads_own_field(text, field) for sf, text in cs
                   if sf.rel in {d[0].rel for d in owners}):
                continue  # z. B. berechnete Eigenschaft im Modell selbst
            owner = " / ".join(sorted({f"{o[1]}.{field}" for o in owners}))
            line = _line_of(vm_text, pos)
            findings.append(Finding(
                check_id=CID, severity=Severity.WARNING,
                message=f"{owner} wird hier in {prop} geladen und zurückgeschrieben, "
                        "außerhalb dieses Editors aber nirgends gelesen: die Einstellung "
                        "wird gespeichert, wirkt aber nicht.",
                file=vm.rel, line=line, evidence=snippet(_raw_line(vm, line)),
                fix=f"Den Verbraucher anbinden (Berechnung/Dienst liest {field} statt "
                    "eines festen Werts) — oder das Feld samt Editor entfernen.",
            ))
    return result_for(CID, TITLE, findings, units, "bearbeitete Modellfelder", PLATFORM)
