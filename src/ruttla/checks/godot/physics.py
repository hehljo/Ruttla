"""Godot hitbox, movement and moving-target checks, split without behavior changes."""

from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, snippet, strip_comments,
)

from ._common import PLATFORM, _gd


@register(
    "godot.instant_hitbox_overlapping_bodies",
    "Kurzlebige Hitbox nutzt get_overlapping_bodies() statt PhysicsDirectSpaceState2D.intersect_shape()",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Physik",
    self_tests=[
        SelfTestCase(
            name="Hitbox mit get_overlapping_bodies nach await physics_frame",
            files={
                "scripts/whip.gd": (
                    "extends Node2D\n"
                    "func strike():\n"
                    "\tvar a = Area2D.new()\n"
                    "\tawait get_tree().physics_frame\n"
                    "\tfor b in a.get_overlapping_bodies():\n"
                    "\t\tb.take_damage(10)\n"
                )
            },
            expect=Status.FAIL,
            expect_finding_contains="get_overlapping_bodies",
        ),
        SelfTestCase(
            name="Legitimer get_overlapping_bodies Aufruf ohne await",
            files={
                "scripts/zone.gd": (
                    "extends Area2D\n"
                    "func check_occupants():\n"
                    "\tvar count = get_overlapping_bodies().size()\n"
                )
            },
            expect=Status.PASS,
        ),
    ],
)
def check_instant_hitbox_query(ctx: Context) -> CheckResult:
    """In Godot 4 führt get_overlapping_bodies() bei kurzlebigen Hitboxen (wie
    Peitschen-Hieben oder Explosionen) regelmäßig zu Null-Treffern, weil neu erzeugte
    Area2Ds auf bereits überlappende Körper erst nach mehreren Simulations-Ticks reagieren.
    Lösung: Sofortige, synchrone Kollisionsabfrage über
    PhysicsDirectSpaceState2D.intersect_shape(PhysicsShapeQueryParameters2D)."""
    title = "Kurzlebige Hitbox nutzt get_overlapping_bodies() statt intersect_shape()"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.instant_hitbox_overlapping_bodies", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)

    await_physics = re.compile(r"await\s+get_tree\(\)\.physics_frame")
    overlap_pat = re.compile(r"\.get_overlapping_bodies\(\)")

    findings: list[Finding] = []
    measured = 0

    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        if "get_overlapping_bodies" not in body:
            continue
        measured += 1
        lines = sf.lines
        for idx, line in enumerate(lines, start=1):
            if overlap_pat.search(line):
                # Prüfen, ob in den vorherigen 5 Zeilen ein await physics_frame stand (typisches Hitbox-Muster)
                start_window = max(0, idx - 6)
                preceding_text = "\n".join(lines[start_window:idx])
                if await_physics.search(preceding_text):
                    findings.append(Finding(
                        check_id="godot.instant_hitbox_overlapping_bodies",
                        severity=Severity.WARNING,
                        message="Hitbox nutzt 'get_overlapping_bodies()' nach 'await physics_frame' — reagiert bei neuen Area2Ds unzuverlässig.",
                        file=sf.rel,
                        line=idx,
                        evidence=snippet(line),
                        fix="Nutze PhysicsDirectSpaceState2D.intersect_shape(PhysicsShapeQueryParameters2D) für synchrone Treffererfassung.",
                        guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Physik",
                    ))

    if measured == 0:
        return unmeasured("godot.instant_hitbox_overlapping_bodies", title,
                          "Keine get_overlapping_bodies()-Aufrufe gefunden.", PLATFORM)
    return result_for("godot.instant_hitbox_overlapping_bodies", title, findings, measured,
                      "Hitbox-Abfragen", PLATFORM)


@register(
    "godot.physics_movement_in_process",
    "Area2D oder Physics-Knoten wird in _process() bewegt (verursacht Kollisionstunneln)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Physik",
    self_tests=[
        SelfTestCase(
            name="Area2D in _process bewegt",
            files={
                "scripts/bullet.gd": (
                    "extends Area2D\n"
                    "func _process(delta):\n"
                    "\tglobal_position += dir * speed * delta\n"
                )
            },
            expect=Status.FAIL,
            expect_finding_contains="Kollisionstunneln",
        ),
        SelfTestCase(
            name="Area2D in _physics_process bewegt",
            files={
                "scripts/bullet.gd": (
                    "extends Area2D\n"
                    "func _physics_process(delta):\n"
                    "\tglobal_position += dir * speed * delta\n"
                )
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Area2D mit _process ohne Positionsbewegung",
            files={
                "scripts/area.gd": (
                    "extends Area2D\n"
                    "func _process(delta):\n"
                    "\trotation += 1.0 * delta\n"
                )
            },
            expect=Status.PASS,
        ),
    ],
)
def check_physics_movement_in_process(ctx: Context) -> CheckResult:
    """In Godot läuft _process() auf variablen Render-Frames, während der Physikserver
    diskret im festen Takt (z. B. 60 Hz) simuliert. Wenn Area2D-Projektile oder
    Kollisionskörper ihre Position in _process() verändern, interpoliert der Physikserver
    stale Koordinaten und schnelle Projektile (ab ca. 300 px/s) tunneln ohne Treffer
    durch gegnerische Hitboxen.
    Lösung: Positionsaktualisierungen zwingend in _physics_process(delta) ausführen."""
    title = "Area2D oder Physics-Knoten wird in _process() bewegt"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.physics_movement_in_process", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)

    physics_base = re.compile(r"^[ \t]*extends\s+(Area2D|Area3D|CharacterBody2D|CharacterBody3D|RigidBody2D|RigidBody3D)", re.MULTILINE)
    func_process = re.compile(r"^\s*func\s+_process\s*\([^)]*\)")
    func_any = re.compile(r"^\s*func\s+\w+\s*\(")
    pos_move = re.compile(r"\b(?:global_)?position\s*[\+\-\*\/]?=|\btranslate\s*\(")

    findings: list[Finding] = []
    measured = 0

    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        if not physics_base.search(body):
            continue
        if "_process" not in body:
            continue

        measured += 1
        lines = sf.lines
        in_process = False
        process_indent = 0

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if func_process.search(line):
                in_process = True
                process_indent = len(line) - len(line.lstrip())
                continue

            if in_process:
                # Prüfen, ob eine neue Funktion auf gleicher/höherer Ebene beginnt
                if func_any.search(line):
                    curr_indent = len(line) - len(line.lstrip())
                    if curr_indent <= process_indent:
                        in_process = False
                        continue

                if pos_move.search(line):
                    findings.append(Finding(
                        check_id="godot.physics_movement_in_process",
                        severity=Severity.WARNING,
                        message="Kollisions-Knoten (Area2D/Body) bewegt Position in '_process()' — führt zu Kollisionstunneln und verpassten Treffern.",
                        file=sf.rel,
                        line=idx,
                        evidence=snippet(line),
                        fix="Bewege das Projektil/den Körper in '_physics_process(delta)' für synchrone Kollisionsberechnung.",
                        guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Physik",
                    ))

    if measured == 0:
        return unmeasured("godot.physics_movement_in_process", title,
                          "Keine Physics-/Area-Knoten mit _process()-Funktionen gefunden.", PLATFORM)
    return result_for("godot.physics_movement_in_process", title, findings, measured,
                      "Physics-Knoten mit _process()", PLATFORM)


@register(
    "godot.tween_moving_target_position",
    "tween_property() nutzt *.global_position eines Zielknotens für Verfolgung (friert Koordinate statisch ein)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Physik",
    self_tests=[
        SelfTestCase(
            name="Tween auf player.global_position",
            files={
                "scripts/boomerang.gd": (
                    "extends Node2D\n"
                    "func return_home():\n"
                    "\ttween.tween_property(self, \"global_position\", player.global_position, 0.5)\n"
                )
            },
            expect=Status.FAIL,
            expect_finding_contains="global_position",
        ),
        SelfTestCase(
            name="Tween auf feste Zielkoordinate",
            files={
                "scripts/bullet.gd": (
                    "extends Node2D\n"
                    "func launch():\n"
                    "\ttween.tween_property(self, \"global_position\", target_pos, 0.5)\n"
                )
            },
            expect=Status.PASS,
        ),
    ],
)
def check_tween_moving_target_position(ctx: Context) -> CheckResult:
    """In Godot wertet tween.tween_property(..., target_node.global_position) den
    Positionswert genau einmal zum Zeitpunkt des Aufrufs aus. Wenn sich das Ziel
    (z. B. der Spieler) während der Animation bewegt, steuert der Tween die verlassene
    Koordinate an statt dem bewegten Ziel zu folgen.
    Lösung: Dynamisches Tracking in _physics_process(delta) über Richtungsvektoren."""
    title = "tween_property() auf dynamische Knoten-Position für Zielverfolgung"
    files = _gd(ctx)
    if not files:
        return unmeasured("godot.tween_moving_target_position", title,
                          "Keine GDScript-Dateien gefunden.", PLATFORM)

    tween_target_pos = re.compile(
        r'tween_property\s*\(\s*[^,]+,\s*"(?:global_)?position"\s*,\s*(?:player|target|enemy|body)\.(?:global_)?position\b'
    )

    findings: list[Finding] = []
    measured = 0

    for sf in files:
        if "tween_property" not in sf.text:
            continue
        measured += 1
        lines = sf.lines
        for idx, line in enumerate(lines, start=1):
            if tween_target_pos.search(line):
                findings.append(Finding(
                    check_id="godot.tween_moving_target_position",
                    severity=Severity.WARNING,
                    message="tween_property() liest *.position des Zielknotens statisch aus — folgt bewegten Zielen nicht dynamisch.",
                    file=sf.rel,
                    line=idx,
                    evidence=snippet(line),
                    fix="Nutze dynamisches Tracking in '_physics_process(delta)' statt einer statischen Tween-Position.",
                    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Physik",
                ))

    if measured == 0:
        return unmeasured("godot.tween_moving_target_position", title,
                          "Keine tween_property()-Aufrufe gefunden.", PLATFORM)
    return result_for("godot.tween_moving_target_position", title, findings, measured,
                      "Tween-Positionsaufrufe", PLATFORM)
