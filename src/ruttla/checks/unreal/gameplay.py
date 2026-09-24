"""Unreal: collision callbacks and network authority.

Split from the original checks/unreal.py; background and
shared helpers in _common.py.
"""

from __future__ import annotations

import re

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    iter_matches,
    register,
    result_for,
    SelfTestCase,
    Severity,
    snippet,
    Status,
    strip_comments,
    unmeasured,
)

from ._common import (
    _ENGINE_CALLED,
    _HIT_BIND,
    _is_test_file,
    _is_unreal,
    _METHOD_DEF,
    _REPLICATED_FIELD,
    _sources,
    PLATFORM,
)


@register(
    "unreal.hit_binding_without_notify",
    "OnComponentHit gebunden, ohne SetNotifyRigidBodyCollision(true)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 7",
    self_tests=[
        SelfTestCase(
            name="Bindung ohne Notify — Callback feuert nie",
            files={"Source/DemoCtrl.cpp": (
                "#include \"DemoCtrl.h\"\n"
                "UCLASS()\n"
                "class ADemoCtrl : public APlayerController { GENERATED_BODY() };\n"
                "void ADemoCtrl::Bind(UPrimitiveComponent* Mesh)\n"
                "{\n"
                "    Mesh->OnComponentHit.AddDynamic(this, &ADemoCtrl::HandleHit);\n"
                "}\n"
            )},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Notify wird gesetzt",
            files={"Source/DemoCtrl.cpp": (
                "#include \"DemoCtrl.h\"\n"
                "UCLASS()\n"
                "class ADemoCtrl : public APlayerController { GENERATED_BODY() };\n"
                "void ADemoCtrl::Bind(UPrimitiveComponent* Mesh)\n"
                "{\n"
                "    Mesh->SetNotifyRigidBodyCollision(true);\n"
                "    Mesh->OnComponentHit.AddDynamic(this, &ADemoCtrl::HandleHit);\n"
                "}\n"
            )},
            expect=Status.PASS,
        ),
    ],
)
def check_hit_binding_without_notify(ctx: Context) -> CheckResult:
    """Ohne SetNotifyRigidBodyCollision(true) feuert OnComponentHit nie. Der
    fehlende Callback sieht aus wie 'es gab keinen Crash' — ein stilles
    Nicht-Laufen statt eines Fehlers."""
    title = "OnComponentHit gebunden, ohne SetNotifyRigidBodyCollision(true)"
    if not _is_unreal(ctx):
        return unmeasured("unreal.hit_binding_without_notify", title,
                          "Kein Unreal-Projekt erkannt.", PLATFORM)
    files = [f for f in _sources(ctx) if not _is_test_file(f)]
    if not files:
        return unmeasured("unreal.hit_binding_without_notify", title,
                          "Keine C++-Quellen gefunden.", PLATFORM)

    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        if not _HIT_BIND.search(body):
            continue
        for line_no, _m, raw in iter_matches(sf, _HIT_BIND):
            measured += 1
        # Die Prüfung gilt je Datei: irgendwo in derselben Übersetzungseinheit
        # muss das Notify gesetzt werden. Feiner (je Komponente) wäre eine
        # Datenflussanalyse — hier bewusst konservativ, um Falsch-Rot zu meiden.
        if re.search(r"SetNotifyRigidBodyCollision\s*\(\s*true\s*\)", body):
            continue
        first = next(iter_matches(sf, _HIT_BIND), None)
        line_no = first[0] if first else None
        raw = first[2] if first else ""
        findings.append(Finding(
            check_id="unreal.hit_binding_without_notify",
            severity=Severity.ERROR,
            message=("OnComponentHit wird gebunden, aber in dieser Datei ruft "
                     "nichts SetNotifyRigidBodyCollision(true). Der Callback "
                     "feuert dann nie."),
            file=sf.rel, line=line_no, evidence=snippet(raw),
            fix=("Vor der Bindung SetNotifyRigidBodyCollision(true) am selben "
                 "Component aufrufen. Bei Chaos Vehicles ist die Wurzel ein "
                 "SceneComponent ohne Kollision — gebunden wird am SkeletalMesh."),
            guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 7",
        ))
    if measured == 0:
        return unmeasured("unreal.hit_binding_without_notify", title,
                          "Keine OnComponentHit-Bindungen gefunden.", PLATFORM)
    return result_for("unreal.hit_binding_without_notify", title, findings,
                      measured, "Hit-Bindungen", PLATFORM)

@register(
    "unreal.replicated_write_without_authority",
    "Schreibzugriff auf repliziertes Feld ohne HasAuthority()",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 8",
    self_tests=[
        SelfTestCase(
            name="Client schreibt repliziertes Feld",
            files={"Source/DemoState.h": (
                "#pragma once\n"
                "UCLASS()\nclass ADemoState : public AGameStateBase\n{\n"
                "    GENERATED_BODY()\n"
                "private:\n"
                "    UPROPERTY(Replicated) int32 RoundScore;\n"
                "};\n"
            ),
             "Source/DemoState.cpp": (
                "#include \"DemoState.h\"\n"
                "void ADemoState::AddPoints(int32 P)\n"
                "{\n"
                "    RoundScore += P;\n"
                "}\n"
             )},
            expect=Status.FAIL,
            expect_finding_contains="RoundScore",
        ),
        SelfTestCase(
            name="Schreibzugriff hinter HasAuthority()",
            files={"Source/DemoState.h": (
                "#pragma once\n"
                "UCLASS()\nclass ADemoState : public AGameStateBase\n{\n"
                "    GENERATED_BODY()\n"
                "private:\n"
                "    UPROPERTY(Replicated) int32 RoundScore;\n"
                "};\n"
            ),
             "Source/DemoState.cpp": (
                "#include \"DemoState.h\"\n"
                "void ADemoState::AddPoints(int32 P)\n"
                "{\n"
                "    if (!HasAuthority()) return;\n"
                "    RoundScore += P;\n"
                "}\n"
             )},
            expect=Status.PASS,
        ),
    ],
)
def check_replicated_write_without_authority(ctx: Context) -> CheckResult:
    """Ein Client, der lokal schreibt, sieht richtige Werte, bis der Server
    korrigiert — der Fehler zeigt sich als Zucken, nicht als Absturz."""
    title = "Schreibzugriff auf repliziertes Feld ohne HasAuthority()"
    if not _is_unreal(ctx):
        return unmeasured("unreal.replicated_write_without_authority", title,
                          "Kein Unreal-Projekt erkannt.", PLATFORM)
    files = [f for f in _sources(ctx) if not _is_test_file(f)]
    if not files:
        return unmeasured("unreal.replicated_write_without_authority", title,
                          "Keine C++-Quellen gefunden.", PLATFORM)

    names: set[str] = set()
    for sf in files:
        for m in _REPLICATED_FIELD.finditer(strip_comments(sf.text, sf.ext)):
            names.add(m.group(1))
    if not names:
        return unmeasured("unreal.replicated_write_without_authority", title,
                          "Keine UPROPERTY(Replicated)-Felder gefunden.", PLATFORM)

    findings: list[Finding] = []
    measured = 0
    for sf in files:
        if sf.ext not in (".cpp", ".inl"):
            continue
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        # Funktionsgrenzen grob über Definitionsköpfe bestimmen.
        heads = [(m.start(), m.group(2)) for m in _METHOD_DEF.finditer(body)]
        for name in sorted(names):
            write = re.compile(
                r"(?<![\w.>])" + re.escape(name) + r"\s*(?:=(?!=)|\+=|-=|\*=|/=|\+\+|--)"
            )
            for m in write.finditer(body):
                line_no = body.count("\n", 0, m.start()) + 1
                measured += 1
                # Funktion suchen, in der der Schreibzugriff steht.
                fn_start = 0
                fn_name = "?"
                for pos, nm in heads:
                    if pos <= m.start():
                        fn_start, fn_name = pos, nm
                    else:
                        break
                scope = body[fn_start: m.start()]
                guarded = (
                    "HasAuthority" in scope
                    or "GetNetMode" in scope
                    or "ROLE_Authority" in scope
                    or "IsNetMode" in scope
                    # _Implementation von Server-RPCs läuft per Definition
                    # auf dem Server.
                    or fn_name.endswith("_Implementation")
                    or fn_name.startswith(("Server", "OnRep_"))
                    # Konstruktor und GetLifetimeReplicatedProps sind unkritisch.
                    or fn_name in _ENGINE_CALLED
                )
                if guarded:
                    continue
                raw = lines[line_no - 1] if line_no <= len(lines) else ""
                findings.append(Finding(
                    check_id="unreal.replicated_write_without_authority",
                    severity=Severity.WARNING,
                    message=(f"'{name}' ist repliziert und wird in {fn_name}() "
                             f"ohne Autoritätsprüfung geschrieben. Auf einem Client "
                             f"erzeugt das einen Wert, den der Server gleich überschreibt."),
                    file=sf.rel, line=line_no, evidence=snippet(raw),
                    fix=("Schreibzugriff hinter if (!HasAuthority()) return; legen "
                         "oder den Zustand über ein Server-RPC ändern."),
                    guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 8",
                ))
    if measured == 0:
        return unmeasured("unreal.replicated_write_without_authority", title,
                          "Keine Schreibzugriffe auf replizierte Felder gefunden.",
                          PLATFORM)
    return result_for("unreal.replicated_write_without_authority", title, findings,
                      measured, "Schreibzugriffe", PLATFORM)
