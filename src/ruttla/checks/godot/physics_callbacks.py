"""Bounded collider writes in explicitly connected Area physics callbacks.

The real engine rejects shape changes while flushing queries. This advisory
follows direct local helper calls only; dynamic/cross-script reward chains need
an actual-engine project proof. Target code is never executed.
"""
from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, snippet, strip_comments, unmeasured,
)
from ._common import PLATFORM, _gd

_ID = "godot.collider_write_in_physics_signal"
_TITLE = "Collider direkt in einem verbundenen Physiksignal geändert"
_GUIDE = "CODE_QUALITY_GUIDELINES_GAMEDEV.md § Physik"
_BASE = ("extends Area2D\n"
         "@onready var collider: CollisionShape2D = $CollisionShape2D\n"
         "func _ready():\n\tbody_entered.connect(on_contact)\n"
         "func on_contact(body):\n")


@register(
    _ID, _TITLE, platform=PLATFORM, severity=Severity.WARNING,
    guideline=_GUIDE,
    self_tests=[
        SelfTestCase(name="Aufgeschobener Setter", files={"a.gd": _BASE +
                     '\tcollider.set_deferred("disabled", true)\n'}, expect=Status.PASS),
        SelfTestCase(name="Aufgeschobener Helper", files={"a.gd": _BASE +
                     '\tresize.call_deferred()\nfunc resize():\n\tcollider.shape = shape\n'},
                     expect=Status.PASS),
        SelfTestCase(name="Deferred-Verbindung", files={"a.gd":
                     _BASE.replace("connect(on_contact)",
                                   "connect(on_contact, CONNECT_DEFERRED)") +
                     "\tcollider.disabled = true\n"}, expect=Status.PASS),
        SelfTestCase(name="Abgetrennte neue Form", files={"a.gd": _BASE +
                     "\tvar fresh: CollisionShape2D = CollisionShape2D.new()\n"
                     "\tfresh.disabled = true\n"}, expect=Status.PASS),
        SelfTestCase(name="Andere Funktion", files={"a.gd": _BASE +
                     "\tpass\nfunc configure():\n\tcollider.shape = shape\n"}, expect=Status.PASS),
        SelfTestCase(name="Fremder gleichnamiger Helper", files={"a.gd": _BASE +
                     "\tother.resize()\nfunc resize():\n\tcollider.shape = shape\n"}, expect=Status.PASS),
        SelfTestCase(name="Numerisches Deferred-Flag", files={"a.gd":
                     _BASE.replace("connect(on_contact)", "connect(on_contact, 5)") +
                     "\tcollider.disabled = true\n"}, expect=Status.PASS),
        SelfTestCase(name="Unverbundener Callback", files={"a.gd":
                     _BASE.replace("\tbody_entered.connect(on_contact)\n", "\tpass\n") +
                     "\tcollider.shape = shape\n"}, expect=Status.UNMEASURED),
        SelfTestCase(name="Dynamisches Flag", files={"a.gd":
                     _BASE.replace("connect(on_contact)", "connect(on_contact, flags)") +
                     "\tcollider.disabled = true\n"}, expect=Status.UNMEASURED),
        SelfTestCase(name="Await-Pfad unbekannt", files={"a.gd": _BASE +
                     "\tawait get_tree().process_frame\n\tcollider.shape = shape\n"},
                     expect=Status.UNMEASURED),
        SelfTestCase(name="Schattenbindung unbekannt", files={"a.gd": _BASE +
                     "\tvar collider = CollisionShape2D.new()\n\tcollider.disabled = true\n"},
                     expect=Status.UNMEASURED),
        SelfTestCase(name="Closure unbekannt", files={"a.gd": _BASE +
                     "\tvar later = func():\n\t\tcollider.disabled = true\n"},
                     expect=Status.UNMEASURED),
        SelfTestCase(name="Direkt disabled", files={"a.gd": _BASE +
                     "\tcollider.disabled = true\n"}, expect=Status.FAIL),
        SelfTestCase(name="Direkt shape", files={"a.gd": _BASE +
                     "\tcollider.shape = shape\n"}, expect=Status.FAIL),
        SelfTestCase(name="Synchroner lokaler Helper", files={"a.gd": _BASE +
                     "\tresize()\nfunc resize():\n\tcollider.shape = shape\n"}, expect=Status.FAIL),
        SelfTestCase(name="Synchroner self-Helper", files={"a.gd": _BASE +
                     "\tself.resize()\nfunc resize():\n\tcollider.disabled = true\n"}, expect=Status.FAIL),
        SelfTestCase(name="Anderes Physiksignal", files={"a.gd":
                     _BASE.replace("body_entered", "area_exited") +
                     "\tcollider.shape = shape\n"}, expect=Status.FAIL),
    ],
)
def check_physics_callback_colliders(ctx: Context) -> CheckResult:
    findings: list[Finding] = []
    measured = 0
    for sf in _gd(ctx):
        body = strip_comments(sf.text, sf.ext)
        if not re.search(r"^extends\s+Area[23]D\s*$", body, re.M):
            continue
        colliders = re.findall(
            r"^@onready\s+var\s+(\w+)\s*:\s*CollisionShape[23]D\s*=\s*\$[^\n]+$",
            body, re.M,
        )
        if not colliders:
            continue
        headers = list(re.finditer(r"^func\s+(\w+)\s*\([^\n]*", body, re.M))
        functions = {m.group(1): body[m.end():headers[i + 1].start() if i + 1 < len(headers)
                                     else len(body)] for i, m in enumerate(headers)}
        starts = {m.group(1): body.count("\n", 0, m.end()) + 1 for m in headers}
        connects = re.finditer(
            r"^[ \t]*(?:self\.)?(?:body|area)(?:_shape)?_(?:entered|exited)"
            r"\.connect\(\s*(\w+)(?:\s*,\s*([^()\n]+))?\s*\)", body, re.M,
        )
        for connect in connects:
            callback, flags = connect.groups()
            if callback not in functions:
                continue
            if flags:
                flags = flags.strip()
                if flags == "CONNECT_DEFERRED" or re.fullmatch(r"\d+", flags) and int(flags) & 1:
                    measured += 1
                    continue
                if flags != "0":
                    continue  # Dynamic flag semantics are not known.
            measured += 1
            pending, seen = [callback], set()
            unknown = False
            while pending and len(seen) < 64:
                fn = pending.pop()
                if fn in seen or fn not in functions:
                    continue
                seen.add(fn)
                # Await resumption/control-flow is deliberately outside this bounded check.
                if (re.search(r"\bawait\b|\bfunc\s*\(", functions[fn])
                        or any(re.search(r"\bvar\s+" + re.escape(c) + r"\b", functions[fn])
                               for c in colliders)):
                    unknown = True
                    continue
                for offset, line in enumerate(functions[fn].splitlines()):
                    for collider in colliders:
                        if not re.match(r"^\s*(?:self\.)?" + re.escape(collider) +
                                        r"\.(?:disabled|shape)\s*=(?!=)", line):
                            continue
                        line_no = starts[fn] + offset
                        findings.append(Finding(
                            check_id=_ID, severity=Severity.WARNING,
                            message=f"Collider-Zuweisung in '{fn}()' aus '{callback}()': "
                                    "Physiksignal kann noch flushing queries ausführen.",
                            file=sf.rel, line=line_no, evidence=snippet(line),
                            fix="Setter mit set_deferred() oder ganzen Geometrie-Helper "
                                "mit call_deferred() aufschieben; echten Callback testen.",
                            guideline=_GUIDE,
                        ))
                    call = re.match(r"^\s*(?:self\.)?(\w+)\s*\(", line)
                    if call and call.group(1) in functions:
                        pending.append(call.group(1))
            if unknown or pending:
                measured -= 1
    if findings:
        measured = max(measured, 1)
    if not measured:
        return unmeasured(_ID, _TITLE, "Kein statisch verbundener Area-Callback mit "
                          "typisiertem Collider gemessen. Szenen-/Cross-Script-/Await-Pfade "
                          "benötigen einen echten Laufzeitnachweis.", PLATFORM)
    return result_for(_ID, _TITLE, findings, measured,
                      "explizite Area-Signalverbindungen; nur direkte lokale Helper", PLATFORM)
