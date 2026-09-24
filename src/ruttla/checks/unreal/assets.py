"""Unreal: asset loading and modular mesh animation.

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

from ._common import _FINDER, _is_test_file, _is_unreal, _sources, PLATFORM


@register(
    "unreal.objectfinder_silent_failure",
    "FObjectFinder ohne Fehlerzweig — fehlendes Asset bleibt still",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 1a",
    self_tests=[
        SelfTestCase(
            name="Succeeded() ohne else — Pawn spawnt ohne Mesh",
            files={"Source/DemoChar.cpp": (
                "#include \"DemoChar.h\"\n"
                "UCLASS()\n"
                "class ADemoChar : public ACharacter { GENERATED_BODY() };\n"
                "ADemoChar::ADemoChar()\n"
                "{\n"
                "    static ConstructorHelpers::FObjectFinder<USkeletalMesh> BaseMesh(\n"
                "        TEXT(\"/Game/Character/SKM_Base.SKM_Base\"));\n"
                "    if (BaseMesh.Succeeded())\n"
                "    {\n"
                "        GetMesh()->SetSkeletalMeshAsset(BaseMesh.Object);\n"
                "    }\n"
                "}\n"
            )},
            expect=Status.FAIL,
            expect_finding_contains="BaseMesh",
        ),
        SelfTestCase(
            name="Fehlerfall wird geloggt",
            files={"Source/DemoChar.cpp": (
                "#include \"DemoChar.h\"\n"
                "UCLASS()\n"
                "class ADemoChar : public ACharacter { GENERATED_BODY() };\n"
                "ADemoChar::ADemoChar()\n"
                "{\n"
                "    static ConstructorHelpers::FObjectFinder<USkeletalMesh> BaseMesh(\n"
                "        TEXT(\"/Game/Character/SKM_Base.SKM_Base\"));\n"
                "    if (BaseMesh.Succeeded())\n"
                "    {\n"
                "        GetMesh()->SetSkeletalMeshAsset(BaseMesh.Object);\n"
                "    }\n"
                "    else\n"
                "    {\n"
                "        UE_LOG(LogTemp, Error, TEXT(\"DEMO_MESH_MISSING=True\"));\n"
                "    }\n"
                "}\n"
            )},
            expect=Status.PASS,
        ),
    ],
)
def check_objectfinder_silent_failure(ctx: Context) -> CheckResult:
    """Findet der Finder das Asset nicht, ist Succeeded() schlicht false: kein
    Absturz, keine rote Automation. Der Pawn spawnt OHNE Mesh und der
    Entwickler sucht danach in der Bewegungslogik."""
    title = "FObjectFinder ohne Fehlerzweig — fehlendes Asset bleibt still"
    if not _is_unreal(ctx):
        return unmeasured("unreal.objectfinder_silent_failure", title,
                          "Kein Unreal-Projekt erkannt.", PLATFORM)
    files = _sources(ctx)
    if not files:
        return unmeasured("unreal.objectfinder_silent_failure", title,
                          "Keine C++-Quellen gefunden.", PLATFORM)

    findings: list[Finding] = []
    measured = 0
    for sf in files:
        if _is_test_file(sf):
            continue
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for line_no, m, raw in iter_matches(sf, _FINDER):
            measured += 1
            var = m.group(1)
            # Im Rest der Funktion nach einer Fehlerbehandlung suchen:
            # ein else-Zweig, ein !Succeeded(), ein check()/ensure(), oder
            # ein Log mit dem Variablennamen in der Nähe.
            window = "\n".join(lines[line_no - 1: line_no + 40])
            handled = (
                re.search(r"\belse\b", window)
                or re.search(r"!\s*" + re.escape(var) + r"\s*\.\s*Succeeded\s*\(", window)
                or re.search(r"\b(?:check|checkf|ensure|ensureMsgf|verify)\s*\(\s*"
                             + re.escape(var), window)
                or re.search(r"UE_LOG\s*\(\s*\w+\s*,\s*(?:Error|Fatal|Warning)", window)
            )
            if handled:
                continue
            findings.append(Finding(
                check_id="unreal.objectfinder_silent_failure",
                severity=Severity.ERROR,
                message=(f"'{var}' wird ohne Fehlerzweig benutzt. Fehlt das Asset, "
                         f"ist Succeeded() false — der Actor entsteht ohne Mesh/Klasse "
                         f"und nichts meldet es."),
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix=(f"else-Zweig ergänzen: "
                     f"else {{ UE_LOG(LogTemp, Error, TEXT(\"<MARKER>_MISSING=True|Path=...\")); }} "
                     f"— der Marker macht den Fall im Runtime-Smoke sichtbar."),
                guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 1a",
            ))
    return result_for("unreal.objectfinder_silent_failure", title, findings,
                      measured, "FObjectFinder-Stellen", PLATFORM)


# ---------------------------------------------------------------------------
# § 1c — modulare Meshes ohne Leader-Pose
# ---------------------------------------------------------------------------

@register(
    "unreal.modular_mesh_without_leader_pose",
    "Modulare SkeletalMeshes ohne SetLeaderPoseComponent — T-Pose",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 1c",
    self_tests=[
        SelfTestCase(
            name="Mehrere Meshes, keine Kopplung",
            files={"Source/DemoChar.cpp": (
                "#include \"DemoChar.h\"\n"
                "UCLASS()\n"
                "class ADemoChar : public ACharacter { GENERATED_BODY() };\n"
                "ADemoChar::ADemoChar()\n"
                "{\n"
                "    VisibleBody = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT(\"Body\"));\n"
                "    VisibleBody->SetupAttachment(GetMesh());\n"
                "    VisibleHead = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT(\"Head\"));\n"
                "    VisibleHead->SetupAttachment(GetMesh());\n"
                "}\n"
            )},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Kopplung vorhanden",
            files={"Source/DemoChar.cpp": (
                "#include \"DemoChar.h\"\n"
                "UCLASS()\n"
                "class ADemoChar : public ACharacter { GENERATED_BODY() };\n"
                "ADemoChar::ADemoChar()\n"
                "{\n"
                "    VisibleBody = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT(\"Body\"));\n"
                "    VisibleBody->SetupAttachment(GetMesh());\n"
                "    VisibleHead = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT(\"Head\"));\n"
                "    VisibleHead->SetupAttachment(GetMesh());\n"
                "}\n"
                "void ADemoChar::BeginPlay()\n"
                "{\n"
                "    Super::BeginPlay();\n"
                "    VisibleBody->SetLeaderPoseComponent(GetMesh(), true, false);\n"
                "    VisibleHead->SetLeaderPoseComponent(GetMesh(), true, false);\n"
                "}\n"
            )},
            expect=Status.PASS,
        ),
    ],
)
def check_modular_mesh_leader_pose(ctx: Context) -> CheckResult:
    """Ein modulares Mesh ohne eigene AnimInstance und ohne
    SetLeaderPoseComponent bleibt in der Bind-Pose. Für die Engine ist das kein
    Fehler, nur für den Betrachter: die Figur läuft korrekt und steht in T-Pose."""
    title = "Modulare SkeletalMeshes ohne SetLeaderPoseComponent — T-Pose"
    if not _is_unreal(ctx):
        return unmeasured("unreal.modular_mesh_without_leader_pose", title,
                          "Kein Unreal-Projekt erkannt.", PLATFORM)
    files = [f for f in _sources(ctx) if not _is_test_file(f)]
    if not files:
        return unmeasured("unreal.modular_mesh_without_leader_pose", title,
                          "Keine C++-Quellen gefunden.", PLATFORM)

    sub = re.compile(
        r"CreateDefaultSubobject\s*<\s*USkeletalMeshComponent\s*>\s*\(\s*TEXT\s*\(\s*\"(\w+)\""
    )
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        extra = sub.findall(body)
        if len(extra) < 2:
            # Weniger als zwei zusätzliche Meshes: kein modularer Aufbau.
            continue
        measured += len(extra)
        if re.search(r"SetLeaderPoseComponent\s*\(", body):
            continue
        first = next(iter_matches(sf, sub), None)
        findings.append(Finding(
            check_id="unreal.modular_mesh_without_leader_pose",
            severity=Severity.WARNING,
            message=(f"{len(extra)} zusätzliche SkeletalMeshComponents "
                     f"({', '.join(extra[:4])}) ohne SetLeaderPoseComponent. "
                     f"Ohne Kopplung stehen sie in der Bind-Pose (T-Pose), "
                     f"während die Figur korrekt läuft."),
            file=sf.rel, line=first[0] if first else None,
            evidence=snippet(first[2]) if first else None,
            fix=("Jedes modulare Mesh OHNE eigene AnimInstance an das Basismesh "
                 "koppeln: Mesh->SetLeaderPoseComponent(BaseMesh, true, false). "
                 "Meshes MIT eigener AnimInstance dürfen NICHT gekoppelt werden."),
            guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 1c",
        ))
    if measured == 0:
        return unmeasured("unreal.modular_mesh_without_leader_pose", title,
                          "Kein modularer Mesh-Aufbau gefunden (< 2 Zusatz-Meshes).",
                          PLATFORM)
    return result_for("unreal.modular_mesh_without_leader_pose", title, findings,
                      measured, "Zusatz-Meshes", PLATFORM)
