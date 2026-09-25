"""
Godot/Gamedev-Checks aus CODE_QUALITY_GUIDELINES_GAMEDEV.md.

Schwerpunkte (jeweils mit dem belegten Fall aus der Guideline):
* § 7 Reihenfolge: Werte setzen, BEVOR _ready() läuft — belegt 02.09.2026:
      20 Fußgänger im Baum, 0 in Bewegung.
* § Physik: Abfrage an den Simulationsserver vor dessen erstem Schritt misst
      nichts — 18 Raycasts, null Treffer, und die Prüfung meldete "alles frei".
* § Warnung pro Frame ist Lärm — 180 gleichlautende Zeilen verdeckten einen Bug.
* § 3 Balancewerte gehören in Daten, nicht in Konstanten.
* § 4 Kommunikation über Signale, nicht über Direktzugriff (get_node("../..")).
"""

from __future__ import annotations

import os
import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, iter_matches, snippet, strip_comments,
)

PLATFORM = "godot"


def _gd(ctx: Context):
    return ctx.files(".gd")


@register(
    "godot.add_child_before_configure",
    "add_child() vor dem Setzen der Werte, die _ready() liest",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 7",
    self_tests=[
        SelfTestCase(
            name="Reihenfolge falsch herum",
            files={"src/zone.gd": (
                "extends Node\n"
                "func spawn():\n"
                "\tvar p = SCENE.instantiate()\n"
                "\tadd_child(p)\n"
                "\tp.marker_path = $Markers.get_path()\n"
            )},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Werte zuerst",
            files={"src/zone.gd": (
                "extends Node\n"
                "func spawn():\n"
                "\tvar p = SCENE.instantiate()\n"
                "\tp.marker_path = $Markers.get_path()\n"
                "\tadd_child(p)\n"
            )},
            expect=Status.PASS,
        ),
    ],
)
def check_add_child_order(ctx: Context) -> CheckResult:
    """_ready() läuft beim add_child() und liest sofort. Ein danach gesetzter
    Wert erreicht niemanden — der Knoten steht sichtbar da und tut nichts."""
    title = "add_child() vor dem Setzen der Werte, die _ready() liest"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.add_child_before_configure", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)
    add_child = re.compile(r"^(\s*)(?:\w+\.)?add_child\s*\(\s*(\w+)\s*[,)]")
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for idx, raw in enumerate(lines):
            m = add_child.match(raw)
            if not m:
                continue
            measured += 1
            var = m.group(2)
            # Nach dem add_child: wird am selben Knoten noch etwas gesetzt?
            assign = re.compile(
                r"^\s*" + re.escape(var) + r"\.(\w+)\s*=\s*(?!=)"
            )
            for off in range(idx + 1, min(len(lines), idx + 12)):
                nxt = lines[off]
                # Ende des Blocks (Ausrückung) beendet die Betrachtung.
                if nxt.strip() and not nxt.startswith(m.group(1)):
                    break
                am = assign.match(nxt)
                if not am:
                    continue
                orig = sf.lines[off] if off < len(sf.lines) else nxt
                findings.append(Finding(
                    check_id="godot.add_child_before_configure",
                    severity=Severity.ERROR,
                    message=f"'{var}.{am.group(1)}' wird NACH add_child() gesetzt — "
                            "_ready() hat den alten Wert gelesen.",
                    file=sf.rel, line=off + 1, evidence=snippet(orig),
                    fix="Alle Werte VOR add_child() setzen. 'Wird gesetzt' ist "
                        "keine Aussage über 'kommt an'.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 7",
                ))
                break
    if measured == 0:
        return unmeasured("godot.add_child_before_configure", title,
                          "Kein add_child()-Aufruf gefunden.", PLATFORM)
    return result_for("godot.add_child_before_configure", title, findings,
                      measured, "add_child-Aufrufe", PLATFORM)


@register(
    "godot.physics_query_before_first_step",
    "Physik-Abfrage im Aufbau, bevor der Server einen Schritt gemacht hat",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Physik",
    self_tests=[
        SelfTestCase(
            name="Raycast im Aufbau",
            files={"src/z.gd": "extends Node\nfunc spawn_all():\n\tvar s = get_world_3d().direct_space_state\n\ts.intersect_ray(q)\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="nach physics_frame",
            files={"src/z.gd": "extends Node\nfunc spawn_all():\n\tawait get_tree().physics_frame\n\tvar s = get_world_3d().direct_space_state\n\ts.intersect_ray(q)\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_physics_timing(ctx: Context) -> CheckResult:
    """Belegt 02.09.2026: 18 Raycasts, null Treffer — die Kollisionsformen sind
    im Erzeugungspfad noch nicht im Physikserver registriert. Der Strahl liefert
    "kein Treffer", was wie ein Ergebnis aussieht."""
    title = "Physik-Abfrage im Aufbau, bevor der Server einen Schritt gemacht hat"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.physics_query_before_first_step", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)
    query = re.compile(
        r"(intersect_ray|intersect_point|intersect_shape|cast_motion|"
        r"get_direct_space_state|test_move|move_and_collide)"
    )
    setup_fn = re.compile(r"^\s*func\s+(_ready|_init|_enter_tree|spawn\w*|setup\w*|"
                          r"create\w*|build\w*|generate\w*)\s*\(")
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        current_fn: str | None = None
        fn_start = 0
        for idx, raw in enumerate(lines):
            fm = setup_fn.match(raw)
            if fm:
                current_fn, fn_start = fm.group(1), idx
                continue
            if re.match(r"^\s*func\s+", raw):
                current_fn = None
                continue
            if current_fn is None:
                continue
            if not query.search(raw):
                continue
            measured += 1
            # Ein await auf process_frame/physics_frame vor der Abfrage heilt es.
            window = "\n".join(lines[fn_start: idx])
            if re.search(r"await\s+get_tree\(\)\.(physics_frame|process_frame)", window):
                continue
            orig = sf.lines[idx] if idx < len(sf.lines) else raw
            findings.append(Finding(
                check_id="godot.physics_query_before_first_step",
                severity=Severity.ERROR,
                message=f"Physik-Abfrage in '{current_fn}()' — die Kollisionsformen "
                        "sind dort noch nicht registriert.",
                file=sf.rel, line=idx + 1, evidence=snippet(orig),
                fix="'await get_tree().physics_frame' davor, oder die Abfrage in "
                    "einen nachgelagerten Durchgang legen. Und 'null Treffer bei "
                    "n Abfragen' ist rot, nicht 'alles frei'.",
                guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Physik",
            ))
    if measured == 0:
        return unmeasured("godot.physics_query_before_first_step", title,
                          "Keine Physik-Abfragen in Aufbaufunktionen gefunden.",
                          PLATFORM)
    return result_for("godot.physics_query_before_first_step", title, findings,
                      measured, "Physik-Abfragen", PLATFORM)


@register(
    "godot.warning_in_hot_loop",
    "Warnung/Ausgabe in _process/_physics_process — Lärm pro Frame",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Lärm",
    self_tests=[
        SelfTestCase(
            name="push_warning im _process",
            files={"src/a.gd": "extends Node\nfunc _process(delta):\n\tif not target:\n\t\tpush_warning(\"kein Ziel\")\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="nur beim Wechsel",
            files={"src/a.gd": "extends Node\nvar _warned := false\nfunc _process(delta):\n\tif not target and not _warned:\n\t\t_warned = true\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_hot_loop_logging(ctx: Context) -> CheckResult:
    """180 gleichlautende Warnungen in einem grünen Gate-Lauf verdeckten einen
    Bug, wegen dem kein Verkehrsauto je die Fahrspur wechseln konnte."""
    title = "Warnung/Ausgabe in _process/_physics_process — Lärm pro Frame"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.warning_in_hot_loop", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)
    hot = re.compile(r"^\s*func\s+(_process|_physics_process|_draw|_input)\s*\(")
    noisy = re.compile(r"\b(print|print_debug|printt|push_warning|push_error|printerr)\s*\(")
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        in_hot: str | None = None
        for idx, raw in enumerate(lines):
            hm = hot.match(raw)
            if hm:
                in_hot = hm.group(1)
                measured += 1
                continue
            if re.match(r"^\s*func\s+", raw):
                in_hot = None
                continue
            if in_hot is None or not noisy.search(raw):
                continue
            orig = sf.lines[idx] if idx < len(sf.lines) else raw
            findings.append(Finding(
                check_id="godot.warning_in_hot_loop", severity=Severity.WARNING,
                message=f"Ausgabe in {in_hot}() — feuert bis zu 60× pro Sekunde.",
                file=sf.rel, line=idx + 1, evidence=snippet(orig),
                fix="Nur beim WECHSEL des Befunds melden (Merker mitführen) und "
                    "den Befund selbst in ein Gate legen, das aus der Quelle misst.",
                guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md",
            ))
    if measured == 0:
        return unmeasured("godot.warning_in_hot_loop", title,
                          "Keine _process/_physics_process-Funktionen gefunden.",
                          PLATFORM)
    return result_for("godot.warning_in_hot_loop", title, findings, measured,
                      "heiße Schleifen", PLATFORM)


@register(
    "godot.allocation_in_hot_loop",
    "Allokation oder I/O in _process/_physics_process",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CLAUDE.md § 'Frequenz mal Kardinalität'",
    self_tests=[
        SelfTestCase(
            name="get_node pro Frame",
            files={"src/a.gd": "extends Node\nfunc _process(delta):\n\tvar t = get_node(\"Target\")\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="einmal in _ready",
            files={"src/a.gd": "extends Node\nvar t\nfunc _ready():\n\tt = get_node(\"Target\")\nfunc _process(delta):\n\tt.position.x += delta\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_hot_loop_alloc(ctx: Context) -> CheckResult:
    """Arbeit auf einem heißen Pfad ist nie 'eine Zeile': pro Frame × pro
    Element × pro Empfänger. Drei Faktoren, die sich multiplizieren."""
    title = "Allokation oder I/O in _process/_physics_process"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.allocation_in_hot_loop", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)
    hot = re.compile(r"^\s*func\s+(_process|_physics_process|_draw)\s*\(")
    costly = re.compile(
        r"\b(get_node\s*\(|find_child|find_children|get_children\s*\(|"
        r"\.instantiate\s*\(|load\s*\(|preload\s*\(|FileAccess\.|DirAccess\.|"
        r"ResourceLoader\.|JSON\.|\.new\s*\(|get_tree\(\)\.get_nodes_in_group)"
    )
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        in_hot: str | None = None
        for idx, raw in enumerate(lines):
            hm = hot.match(raw)
            if hm:
                in_hot = hm.group(1)
                measured += 1
                continue
            if re.match(r"^\s*func\s+", raw):
                in_hot = None
                continue
            if in_hot is None:
                continue
            cm = costly.search(raw)
            if not cm:
                continue
            orig = sf.lines[idx] if idx < len(sf.lines) else raw
            findings.append(Finding(
                check_id="godot.allocation_in_hot_loop", severity=Severity.WARNING,
                message=f"'{cm.group(1).strip()}' in {in_hot}() — läuft pro Frame.",
                file=sf.rel, line=idx + 1, evidence=snippet(orig),
                fix="Referenz einmal in _ready() auflösen und zwischenspeichern. "
                    "Vor dem Einbauen Frequenz × Kardinalität rechnen, nicht erst "
                    "beim Ruckeln — und mit n=1 UND n≥15 messen.",
                guideline="CLAUDE.md § Frequenz mal Kardinalität",
            ))
    if measured == 0:
        return unmeasured("godot.allocation_in_hot_loop", title,
                          "Keine heißen Schleifen gefunden.", PLATFORM)
    return result_for("godot.allocation_in_hot_loop", title, findings, measured,
                      "heiße Schleifen", PLATFORM)


@register(
    "godot.fragile_node_path",
    "Zerbrechlicher Knotenpfad statt Signal oder exportierter Referenz",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 4",
    self_tests=[
        SelfTestCase(
            name="Aufwaertspfad",
            files={"src/a.gd": "extends Node\nfunc go():\n\tvar n = get_node(\"../../Manager\")\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="exportierter Pfad",
            files={"src/a.gd": "extends Node\n@export var manager_path: NodePath\nfunc go():\n\tvar n = get_node(manager_path)\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_node_paths(ctx: Context) -> CheckResult:
    """get_node("../../Sibling") koppelt an die Baumstruktur — jede Umstellung
    der Szene bricht ihn, und zwar erst zur Laufzeit."""
    title = "Zerbrechlicher Knotenpfad statt Signal oder exportierter Referenz"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.fragile_node_path", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)
    pat = re.compile(r"(get_node\s*\(\s*[\"']|\$)(\.\./[^\"')\s]*)")
    findings: list[Finding] = []
    for sf in files:
        for line_no, m, raw in iter_matches(sf, pat):
            findings.append(Finding(
                check_id="godot.fragile_node_path", severity=Severity.WARNING,
                message=f"Aufwärtspfad '{snippet(m.group(2), 40)}' koppelt an die "
                        "Baumstruktur.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Über ein Signal nach oben kommunizieren oder den Knoten als "
                    "@export NodePath hereingeben.",
                guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 4",
            ))
    return result_for("godot.fragile_node_path", title, findings, len(files),
                      "GDScript-Dateien", PLATFORM)


@register(
    "godot.balance_value_in_code",
    "Balancewert steht als Konstante im Code statt in Daten",
    platform=PLATFORM,
    severity=Severity.INFO,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 3",
    self_tests=[
        SelfTestCase(
            name="Balancewert als const",
            files={"src/a.gd": "extends Node\nconst MAX_HEALTH := 100\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="aus Resource",
            files={"src/a.gd": "extends Node\n@export var stats: Resource\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_balance_values(ctx: Context) -> CheckResult:
    title = "Balancewert steht als Konstante im Code statt in Daten"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.balance_value_in_code", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)
    pat = re.compile(
        r"^[ \t]*const\s+(\w*(?:SPEED|DAMAGE|HEALTH|HP|COST|PRICE|REWARD|"
        r"DURATION|COOLDOWN|CHANCE|RATE|AMOUNT|MAX_\w+|MIN_\w+)\w*)\s*"
        # GDScript kennt 'const X = 1', 'const X := 1' und 'const X: int = 1'.
        r"(?::\s*\w*\s*)?=\s*[-\d.]+",
        # MULTILINE ist Pflicht: iter_matches sucht mit finditer über den GANZEN
        # Text, dort ankert '^' sonst nur am Dateianfang. Die Gegenprobe hat das
        # gefunden — der Regex war für sich richtig und traf trotzdem nie.
        re.IGNORECASE | re.MULTILINE,
    )
    has_data = any(
        sf.ext in (".tres", ".json", ".cfg") or "data" in sf.rel.lower()
        for sf in ctx.all_files()
    )
    findings: list[Finding] = []
    for sf in files:
        for line_no, m, raw in iter_matches(sf, pat):
            findings.append(Finding(
                check_id="godot.balance_value_in_code", severity=Severity.INFO,
                message=f"Balancewert '{m.group(1)}' als Konstante im Code.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="In eine Resource (.tres) oder Datendatei legen — Balancing "
                    "ohne Neubau änderbar." + ("" if has_data else
                    " Im Projekt gibt es noch keine Datenablage dafür."),
                guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 3",
            ))
    return result_for("godot.balance_value_in_code", title, findings, len(files),
                      "GDScript-Dateien", PLATFORM)


@register(
    "godot.untyped_declaration",
    "Variable oder Rückgabewert ohne Typangabe",
    platform=PLATFORM,
    severity=Severity.INFO,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § 7",
    self_tests=[
        SelfTestCase(
            name="untypisiert",
            files={"src/a.gd": "extends Node\nvar speed = 5.0\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="typisiert",
            files={"src/a.gd": "extends Node\nvar speed := 5.0\nfunc go() -> void:\n\tpass\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_typing(ctx: Context) -> CheckResult:
    """Typisierte Arrays fangen den 'Name in Daten ist ein ungeprüfter Verweis'-
    Fehler beim Bauen statt zur Laufzeit ab."""
    title = "Variable oder Rückgabewert ohne Typangabe"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.untyped_declaration", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)
    untyped_var = re.compile(r"^\s*(?:@export\s+)?var\s+(\w+)\s*=\s*(?!.*:=)")
    untyped_fn = re.compile(r"^\s*func\s+(\w+)\s*\([^)]*\)\s*:\s*$")
    any_decl = re.compile(r"^\s*(?:@export\s+)?var\s+\w+|^\s*func\s+\w+\s*\(")
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        for idx, raw in enumerate(body.splitlines(), start=1):
            # Der Prüfgegenstand ist JEDE Deklaration — nur Verstöße zu zählen
            # macht aus einem gesunden Projekt ein "nicht gemessen".
            if any_decl.match(raw):
                measured += 1
            if untyped_var.match(raw) and ":=" not in raw and ":" not in raw.split("=")[0]:
                orig = sf.lines[idx - 1] if idx <= len(sf.lines) else raw
                findings.append(Finding(
                    check_id="godot.untyped_declaration", severity=Severity.INFO,
                    message=f"'var {untyped_var.match(raw).group(1)}' ohne Typ.",
                    file=sf.rel, line=idx, evidence=snippet(orig),
                    fix="':=' oder eine explizite Typangabe verwenden.",
                ))
            fm = untyped_fn.match(raw)
            if fm and not fm.group(1).startswith("_"):
                orig = sf.lines[idx - 1] if idx <= len(sf.lines) else raw
                findings.append(Finding(
                    check_id="godot.untyped_declaration", severity=Severity.INFO,
                    message=f"'func {fm.group(1)}' ohne Rückgabetyp.",
                    file=sf.rel, line=idx, evidence=snippet(orig),
                    fix="'-> void' oder den tatsächlichen Typ ergänzen.",
                ))
    if measured == 0:
        return unmeasured("godot.untyped_declaration", title,
                          "Keine untypisierten Deklarationen gefunden.", PLATFORM)
    return result_for("godot.untyped_declaration", title, findings, measured,
                      "Deklarationen", PLATFORM)


@register(
    "godot.fixed_wait_instead_of_state",
    "Feste Wartezeit statt Warten auf einen Zustand",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CLAUDE.md § 'Eine feste Wartezeit misst den Zufall'",
    self_tests=[
        SelfTestCase(
            name="feste Wartezeit",
            files={"src/a.gd": "extends Node\nfunc go():\n\tawait get_tree().create_timer(2.0).timeout\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="auf Signal warten",
            files={"src/a.gd": "extends Node\nfunc go():\n\tawait anim.animation_finished\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_fixed_wait(ctx: Context) -> CheckResult:
    title = "Feste Wartezeit statt Warten auf einen Zustand"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.fixed_wait_instead_of_state", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)
    pat = re.compile(r"await\s+get_tree\(\)\.create_timer\s*\(\s*([\d.]+)")
    findings: list[Finding] = []
    for sf in files:
        for line_no, m, raw in iter_matches(sf, pat):
            findings.append(Finding(
                check_id="godot.fixed_wait_instead_of_state",
                severity=Severity.WARNING,
                message=f"Feste Wartezeit von {m.group(1)}s.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Auf den Zustand warten (Signal, Bedingung), mit Obergrenze "
                    "als Endlosschutz — deren Ablauf ist kein Erfolgsfall.",
                guideline="CLAUDE.md § Zustand, Zeit und Nebenläufigkeit",
            ))
    return result_for("godot.fixed_wait_instead_of_state", title, findings,
                      len(files), "GDScript-Dateien", PLATFORM)


@register(
    "godot.missing_main_scene",
    "Hauptszene in project.godot existiert nicht im Dateisystem",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Projektstruktur",
    self_tests=[
        SelfTestCase(
            name="Hauptszene fehlt",
            files={
                "project.godot": '[application]\nconfig/name="Test"\nrun/main_scene="res://scenes/missing.tscn"\n',
            },
            expect=Status.FAIL,
            expect_finding_contains="missing.tscn",
        ),
        SelfTestCase(
            name="Hauptszene existiert",
            files={
                "project.godot": '[application]\nconfig/name="Test"\nrun/main_scene="res://scenes/main.tscn"\n',
                "scenes/main.tscn": '[gd_scene format=3]\n',
            },
            expect=Status.PASS,
        ),
    ],
)
def check_missing_main_scene(ctx: Context) -> CheckResult:
    """Prüft, ob die konfigurierte Hauptszene tatsächlich existiert.
    Eine fehlende Hauptszene bricht Godot sofort beim Start ab."""
    title = "Hauptszene in project.godot existiert nicht im Dateisystem"
    project_files = ctx.files_named("project.godot")
    if not project_files:
        return unmeasured("godot.missing_main_scene", title,
                          "Keine project.godot-Datei gefunden.", PLATFORM)
    pat = re.compile(r'run/main_scene\s*=\s*"res://([^"]+)"')
    findings: list[Finding] = []
    measured = 0
    all_rel_paths = {sf.rel for sf in ctx.all_files()}

    for pf in project_files:
        for idx, line in enumerate(pf.lines, start=1):
            m = pat.search(line)
            if not m:
                continue
            measured += 1
            rel_scene = m.group(1)
            # Im Dateisystem oder ctx.all_files suchen
            target_full = os.path.join(ctx.root, rel_scene)
            if not os.path.isfile(target_full) and rel_scene not in all_rel_paths:
                findings.append(Finding(
                    check_id="godot.missing_main_scene",
                    severity=Severity.ERROR,
                    message=f"Hauptszene 'res://{rel_scene}' existiert nicht im Projektverzeichnis.",
                    file=pf.rel,
                    line=idx,
                    evidence=snippet(line),
                    fix=f"Szene unter '{rel_scene}' anlegen oder Pfad in project.godot korrigieren.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Projektstruktur",
                ))

    return result_for("godot.missing_main_scene", title, findings, measured,
                      "Hauptszenen-Einträge", PLATFORM)


@register(
    "godot.rpc_sender_identity",
    "any_peer-RPC ohne Verifikation der Absender-ID (get_remote_sender_id)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Netzwerk & Multiplayer",
    self_tests=[
        SelfTestCase(
            name="any_peer ohne Absenderpruefung",
            files={
                "src/net.gd": "@rpc(\"any_peer\", \"reliable\")\nfunc submit(data: Dictionary) -> void:\n\tprocess_data(data)\n",
            },
            expect=Status.FAIL,
            expect_finding_contains="submit",
        ),
        SelfTestCase(
            name="any_peer mit Absenderpruefung",
            files={
                "src/net.gd": "@rpc(\"any_peer\", \"reliable\")\nfunc submit(data: Dictionary) -> void:\n\tvar s := multiplayer.get_remote_sender_id()\n\tprocess_data(s, data)\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_rpc_sender_identity(ctx: Context) -> CheckResult:
    """Funktionen mit @rpc('any_peer') dürfen eingehenden Parametern nicht blind
    vertrauen, sondern müssen den Absender über multiplayer.get_remote_sender_id()
    validieren, um Spoofing und Fremdsteuerung zu verhindern."""
    title = "any_peer-RPC ohne Verifikation der Absender-ID (get_remote_sender_id)"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.rpc_sender_identity", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)

    rpc_any_peer = re.compile(r'@rpc\s*\([^)]*["\']any_peer["\'][^)]*\)')
    func_decl = re.compile(r'^\s*func\s+(\w+)\s*\(([^)]*)\)')

    findings: list[Finding] = []
    measured = 0

    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for idx, line in enumerate(lines):
            if not rpc_any_peer.search(line):
                continue

            # Suche die zugehörige Funktionsdeklaration in den nächsten 3 Zeilen
            func_name = None
            func_line = idx + 1
            for look_idx in range(idx + 1, min(len(lines), idx + 4)):
                fm = func_decl.match(lines[look_idx])
                if fm:
                    func_name = fm.group(1)
                    func_line = look_idx + 1
                    break

            if not func_name:
                continue

            measured += 1
            # Durchsuche den Funktionsrumpf bis zur nächsten Funktion oder EOF
            body_lines: list[str] = []
            for b_idx in range(func_line, len(lines)):
                b_line = lines[b_idx]
                if re.match(r'^\s*func\s+|^@rpc', b_line):
                    break
                body_lines.append(b_line)

            func_body = "\n".join(body_lines)
            if "get_remote_sender_id()" not in func_body:
                orig = sf.lines[func_line - 1] if func_line <= len(sf.lines) else line
                findings.append(Finding(
                    check_id="godot.rpc_sender_identity",
                    severity=Severity.ERROR,
                    message=f"RPC-Methode '{func_name}()' ist 'any_peer', prüft aber nicht "
                            "'multiplayer.get_remote_sender_id()'.",
                    file=sf.rel,
                    line=func_line,
                    evidence=snippet(orig),
                    fix="Absender mit 'multiplayer.get_remote_sender_id()' ermitteln und gegen Session-Autorität prüfen.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Netzwerk & Multiplayer",
                ))

    return result_for("godot.rpc_sender_identity", title, findings, measured,
                      "any_peer-RPCs", PLATFORM)


@register(
    "godot.root_directory_pollution",
    "Szenen- oder Skriptdatei liegt direkt im Projekt-Root",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Projektstruktur",
    self_tests=[
        SelfTestCase(
            name="Szene im Root",
            files={
                "Main.tscn": "[gd_scene format=3]\n",
            },
            expect=Status.FAIL,
            expect_finding_contains="Main.tscn",
        ),
        SelfTestCase(
            name="Saubere Ordnerstruktur",
            files={
                "scenes/main.tscn": "[gd_scene format=3]\n",
                "scripts/main.gd": "extends Node\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_root_pollution(ctx: Context) -> CheckResult:
    """Im Projekt-Root gehören nur project.godot, README, Lizenz und .gitignore.
    Szenen (.tscn) und Skripte (.gd) gehören in dedizierte Unterordner (scenes/, scripts/, tests/)."""
    title = "Szenen- oder Skriptdatei liegt direkt im Projekt-Root"
    findings: list[Finding] = []
    measured = 0

    allowed_root_basenames = {"run.gd", "tests.gd"}

    for sf in ctx.all_files():
        if sf.ext not in (".tscn", ".gd"):
            continue
        measured += 1
        # Wenn im Pfad kein Slash/Backslash ist, liegt die Datei direkt im Root
        if "/" not in sf.rel and "\\" not in sf.rel:
            base_name = os.path.basename(sf.rel)
            if base_name in allowed_root_basenames:
                continue
            findings.append(Finding(
                check_id="godot.root_directory_pollution",
                severity=Severity.WARNING,
                message=f"Datei '{sf.rel}' liegt unstrukturiert im Projekt-Root.",
                file=sf.rel,
                line=1,
                evidence=sf.rel,
                fix="In passende Unterordner verschieben: 'scenes/' für .tscn, 'scripts/' für .gd.",
                guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Projektstruktur",
            ))

    return result_for("godot.root_directory_pollution", title, findings, measured,
                      "Szenen und Skripte", PLATFORM)


@register(
    "godot.hardcoded_ui_text",
    "Sichtbarer Text fest im GDScript statt über tr() oder Translation-Key",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Grundsatz C (Katalogpflicht / i18n)",
    self_tests=[
        SelfTestCase(
            name="Hardcoded Text im Button",
            files={
                "src/ui.gd": 'extends Control\nfunc setup():\n\t$Button.text = "Spiel starten"\n',
            },
            expect=Status.FAIL,
            expect_finding_contains="Spiel starten",
        ),
        SelfTestCase(
            name="Uebersetzt via tr()",
            files={
                "src/ui.gd": 'extends Control\nfunc setup():\n\t$Button.text = tr("BTN_START")\n',
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Reiner Translation-Key in Grossbuchstaben",
            files={
                "src/ui.gd": 'extends Control\nfunc setup():\n\t$Button.text = "BTN_START"\n',
            },
            expect=Status.PASS,
        ),
    ],
)
def check_hardcoded_ui_text(ctx: Context) -> CheckResult:
    """Findet sichtbare UI-Texte, die als wörtliche Zeichenketten in .text oder
    .placeholder_text zugewiesen werden, statt tr() oder Translation-Keys zu nutzen."""
    title = "Sichtbarer Text fest im GDScript statt über tr() oder Translation-Key"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.hardcoded_ui_text", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)

    # Zuweisungen an UI-Text-Eigenschaften
    ui_assign = re.compile(
        r'\b(?:(?:\w+|\$|\$"\w+")\.)?(text|placeholder_text|tooltip_text)\s*=\s*(.+)'
    )
    # Reiner String-Literal: beginnt und endet mit Anführungszeichen
    literal_str = re.compile(r'^"([^"\n]{2,})"$')
    # Reiner Key: mindestens 3 Zeichen, nur Großbuchstaben, Ziffern und Unterstriche
    is_translation_key = re.compile(r'^[A-Z0-9_]{3,}$')

    findings: list[Finding] = []
    measured = 0

    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for idx, line in enumerate(lines, start=1):
            m = ui_assign.search(line)
            if not m:
                continue
            measured += 1
            prop_name = m.group(1)
            rhs = m.group(2).strip()

            str_match = literal_str.match(rhs)
            if not str_match:
                # Kein reines Literal (z. B. tr(...), Variable, Funktionsaufruf) -> sauber
                continue

            raw_text = str_match.group(1).strip()

            # Translation-Key in Großbuchstaben (z. B. "BTN_START") ist in Godot legitim
            if is_translation_key.match(raw_text):
                continue

            # Reine Format-Strings oder Zahlen ignorieren
            if raw_text.startswith("%") or raw_text.isdigit():
                continue

            orig = sf.lines[idx - 1] if idx <= len(sf.lines) else line
            findings.append(Finding(
                check_id="godot.hardcoded_ui_text",
                severity=Severity.WARNING,
                message=f"Hardcoded Anzeigetext in .{prop_name}: \"{snippet(raw_text, 40)}\"",
                file=sf.rel,
                line=idx,
                evidence=snippet(orig),
                fix="Über tr(\"...\") lokalisieren oder als Translation-Key hinterlegen.",
                guideline="CLAUDE.md § Grundsatz C (Katalogpflicht / i18n)",
            ))

    if measured == 0:
        return unmeasured("godot.hardcoded_ui_text", title,
                          "Keine Zuweisungen an UI-Text-Eigenschaften gefunden.", PLATFORM)
    return result_for("godot.hardcoded_ui_text", title, findings, measured,
                      "UI-Text-Zuweisungen", PLATFORM)



