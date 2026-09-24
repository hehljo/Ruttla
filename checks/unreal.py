#!/usr/bin/env python3
"""
Unreal-Engine-Checks aus CODE_QUALITY_GUIDELINES_UNREAL.md.

Schwerpunkte (jeweils mit dem belegten Fall aus dem Audit vom 19.09.2026,
reales Spielprojekt auf UE 5.8):

* § 1a FObjectFinder schlägt STILL fehl — `Succeeded()==false` ohne else-Zweig
      spawnt einen Pawn ohne Mesh. Belegt: zehn hart getippte /Game/…-Pfade in
      einer Datei, jeder bricht lautlos bei einer Umbenennung durch Epic.
* § 1c Leader-Pose — modulare Meshes ohne SetLeaderPoseComponent stehen in
      T-Pose. Belegt: alle Einzelteile korrekt, leader_pose_component=None,
      Figur lief korrekt durch die Stadt und blieb in Bind-Pose.
* § 2   Eine Definition ohne Aufrufer ist keine Fähigkeit. Belegt:
      UDemoHealthComponent::ApplyDamage hatte AUSSERHALB der Tests keinen
      einzigen Aufrufer — die Schadenskomponente konnte keinen Schaden bekommen,
      und das Vertragsgate meldete grün, weil der Name als String existierte.
* § 3   UPROPERTY(Config) ohne Leser ist ein toter Balancewert.
* § 7   OnComponentHit ohne SetNotifyRigidBodyCollision(true) feuert nie —
      der fehlende Callback sieht aus wie "es gab keinen Crash".
* § 8   Zustandsschreiber ohne HasAuthority() — der Client sieht richtige
      Werte, bis der Server korrigiert.

Grundregel dieses Moduls: gezählt werden KANDIDATEN (alle Deklarationen, alle
Bindungen), nicht Treffer. Ein gesundes Projekt meldet "bestanden", nicht
"nicht gemessen".
"""

from __future__ import annotations

import os
import re

from core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, iter_matches, snippet, strip_comments,
)

PLATFORM = "unreal"

# Dateiendungen, die Unreal-C++ tragen.
CPP_EXTS = (".cpp", ".h", ".hpp", ".inl")

# Eine Datei gilt als Testdatei, wenn ihr Name das sagt ODER sie ein
# Automation-Test-Makro enthält. Der Name allein wäre eine Bauform-Annahme.
_TEST_NAME = re.compile(r"(?:test|spec)s?\.(?:cpp|h)$", re.IGNORECASE)
_TEST_MACRO = re.compile(
    r"IMPLEMENT_(?:SIMPLE_|COMPLEX_)?AUTOMATION_TEST|"
    r"IMPLEMENT_CUSTOM_SIMPLE_AUTOMATION_TEST|BEGIN_DEFINE_SPEC"
)


def _is_test_file(sf) -> bool:
    """Testdatei? Name ODER Automation-Makro — die Eigenschaft, nicht der Pfad."""
    if _TEST_NAME.search(os.path.basename(sf.rel)):
        return True
    return bool(_TEST_MACRO.search(sf.text))


def _sources(ctx: Context):
    return ctx.files(*CPP_EXTS)


def _is_unreal(ctx: Context) -> bool:
    """Unreal erkannt an EIGENSCHAFTEN, nicht am Ordnernamen."""
    if ctx.dirs_with_suffix(".uproject"):
        return True
    for f in ctx.all_files():
        if f.ext == ".uproject" or f.rel.lower().endswith(".uplugin"):
            return True
    # Build.cs plus UE-Makros ist der zuverlässigste Fingerabdruck.
    has_build_cs = any(f.rel.endswith("Build.cs") for f in ctx.all_files())
    if has_build_cs:
        return True
    for sf in ctx.files(*CPP_EXTS):
        if re.search(r"\b(?:UCLASS|USTRUCT|GENERATED_BODY|UPROPERTY)\s*\(", sf.text):
            return True
    return False


# ---------------------------------------------------------------------------
# § 1a — FObjectFinder ohne Fehlerbehandlung
# ---------------------------------------------------------------------------

_FINDER = re.compile(
    r"ConstructorHelpers::(?:FObjectFinder|FClassFinder)\s*<[^>]*>\s+(\w+)\s*\(",
)

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
# § 2 — Definition ohne Aufrufer
# ---------------------------------------------------------------------------

# Methodendefinition im .cpp: Rückgabetyp Klasse::Name(
_METHOD_DEF = re.compile(
    r"^[A-Za-z_][\w:<>,\s\*&]*?\b(\w+)::(\w+)\s*\([^;{]*\)\s*(?:const\s*)?"
    r"(?:override\s*)?\{",
    re.MULTILINE,
)

# Namen, die per Definition von der Engine gerufen werden — kein Aufrufer im
# eigenen Code ist dort der Normalfall, nicht der Fehler.
_ENGINE_CALLED = {
    "BeginPlay", "Tick", "EndPlay", "PostInitializeComponents", "BeginDestroy",
    "GetLifetimeReplicatedProps", "SetupInputComponent", "SetupPlayerInputComponent",
    "OnPossess", "OnUnPossess", "PlayerTick", "PostLoad", "Serialize",
    "OnConstruction", "PostEditChangeProperty", "PostInitProperties",
    "OnRep_", "Initialize", "Deinitialize", "ShouldCreateSubsystem",
    "HandleStartingNewPlayer_Implementation", "RunTest", "GetWorld",
    "NativeConstruct", "NativeTick", "NativeOnInitialized", "Destroyed",
    "NotifyActorBeginOverlap", "NotifyActorEndOverlap", "TakeDamage",
    "GetPrivateStaticClass", "StaticClass", "StaticRegisterNatives",
}

# "Handle" steht bewusst NICHT hier: ein Handle*-Name ist nur dann ein
# Callback, wenn er als Delegate GEBUNDEN wird (&Klasse::HandleX). Das
# misst _bound_as_delegate(); der blosse Namensanfang ist eine
# Bauform-Annahme und deckte im Test einen echten Befund zu.
_ENGINE_PREFIX = ("On", "Server", "Client", "Multicast", "K2_", "exec")


def _enclosing_function(text: str, pos: int) -> str | None:
    """Name der Funktion, in der `pos` steht — None, wenn keine gefunden wird.

    Gemessen wird die letzte Definition VOR der Stelle. Das ist eine Näherung,
    reicht aber für die Frage 'ruft mich ein Engine-Callback?'.
    """
    last = None
    for m in _METHOD_DEF.finditer(text):
        if m.start() > pos:
            break
        last = m.group(2)
    return last


def _looks_engine_called(name: str) -> bool:
    if name in _ENGINE_CALLED:
        return True
    # _Implementation/_Validate gehören zu RPCs — die ruft die Engine.
    if name.endswith(("_Implementation", "_Validate")):
        return True
    # UFUNCTION-Callbacks und RPC-Namen: konservativ ausnehmen.
    return name.startswith(_ENGINE_PREFIX)


@register(
    "unreal.definition_without_caller",
    "Gameplay-Methode ohne Aufrufer außerhalb der Tests",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 2",
    self_tests=[
        SelfTestCase(
            name="ApplyDamage nur im Test gerufen",
            files={
                "Source/DemoHealth.cpp": (
                    "#include \"DemoHealth.h\"\n"
                    "UCLASS()\n"
                    "class UDemoHealth : public UActorComponent { GENERATED_BODY() };\n"
                    "float UDemoHealth::ApplyDamage(float Amount)\n"
                    "{\n"
                    "    Health -= Amount;\n"
                    "    return Amount;\n"
                    "}\n"
                ),
                "Source/DemoTests.cpp": (
                    "#include \"DemoHealth.h\"\n"
                    "IMPLEMENT_SIMPLE_AUTOMATION_TEST(FDemoTest, \"Demo.Health\", 1)\n"
                    "bool FDemoTest::RunTest(const FString& P)\n"
                    "{\n"
                    "    UDemoHealth* H = NewObject<UDemoHealth>();\n"
                    "    H->ApplyDamage(34.0f);\n"
                    "    return true;\n"
                    "}\n"
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="ApplyDamage",
        ),
        SelfTestCase(
            name="ApplyDamage aus dem Gameplay gerufen",
            files={
                "Source/DemoHealth.cpp": (
                    "#include \"DemoHealth.h\"\n"
                    "UCLASS()\n"
                    "class UDemoHealth : public UActorComponent { GENERATED_BODY() };\n"
                    "float UDemoHealth::ApplyDamage(float Amount)\n"
                    "{\n"
                    "    Health -= Amount;\n"
                    "    return Amount;\n"
                    "}\n"
                ),
                "Source/DemoVehicle.cpp": (
                    "#include \"DemoHealth.h\"\n"
                    "void ADemoVehicle::HitPedestrian(UDemoHealth* Target)\n"
                    "{\n"
                    "    Target->ApplyDamage(50.0f);\n"
                    "}\n"
                    "void ADemoVehicle::Tick(float Dt)\n"
                    "{\n"
                    "    HitPedestrian(nullptr);\n"
                    "}\n"
                ),
                "Source/DemoTests.cpp": (
                    "#include \"DemoHealth.h\"\n"
                    "IMPLEMENT_SIMPLE_AUTOMATION_TEST(FDemoTest, \"Demo.Health\", 1)\n"
                    "bool FDemoTest::RunTest(const FString& P)\n"
                    "{\n"
                    "    UDemoHealth* H = NewObject<UDemoHealth>();\n"
                    "    H->ApplyDamage(34.0f);\n"
                    "    return true;\n"
                    "}\n"
                ),
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            # Belegt am 19.09.2026: die erste Fassung zaehlte die
            # Header-DEKLARATION als Aufruf und den Aufruf aus derselben
            # Datei als externen Nutzer. Beides machte den echten
            # ApplyDamage-Befund unsichtbar.
            name="Nur Header-Deklaration und datei-interner Aufruf",
            files={
                "Source/DemoHealth.h": (
                    "#pragma once\n"
                    "UCLASS()\n"
                    "class UDemoHealth : public UActorComponent\n"
                    "{\n"
                    "    GENERATED_BODY()\n"
                    "public:\n"
                    "    float ApplyDamage(float DamageAmount);\n"
                    "};\n"
                ),
                "Source/DemoHealth.cpp": (
                    "#include \"DemoHealth.h\"\n"
                    "float UDemoHealth::ApplyDamage(float Amount)\n"
                    "{\n"
                    "    Health -= Amount;\n"
                    "    return Amount;\n"
                    "}\n"
                    "void UDemoHealth::HandleAnyDamage(float D)\n"
                    "{\n"
                    "    ApplyDamage(D);\n"
                    "}\n"
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="ApplyDamage",
        ),
    ],
)
def check_definition_without_caller(ctx: Context) -> CheckResult:
    """Eine Funktion ohne Aufrufer ist keine Fähigkeit. Testdateien zählen
    NICHT mit — sonst hält sich jeder tote Code durch seinen eigenen Unit-Test
    am Leben. Belegt: UDemoHealthComponent::ApplyDamage, monatelang ohne
    Gameplay-Aufrufer, Gate grün."""
    title = "Gameplay-Methode ohne Aufrufer außerhalb der Tests"
    if not _is_unreal(ctx):
        return unmeasured("unreal.definition_without_caller", title,
                          "Kein Unreal-Projekt erkannt.", PLATFORM)
    files = _sources(ctx)
    if not files:
        return unmeasured("unreal.definition_without_caller", title,
                          "Keine C++-Quellen gefunden.", PLATFORM)

    prod = [f for f in files if not _is_test_file(f)]
    if not prod:
        return unmeasured("unreal.definition_without_caller", title,
                          "Nur Testdateien gefunden — kein Produktivcode zu messen.",
                          PLATFORM)

    # Definitionen einsammeln.
    defs: list[tuple[str, str, str, int, str]] = []  # (cls, name, rel, line, raw)
    for sf in prod:
        body = strip_comments(sf.text, sf.ext)
        for m in _METHOD_DEF.finditer(body):
            cls, name = m.group(1), m.group(2)
            if cls == name or name == ("~" + cls):      # Konstruktor/Destruktor
                continue
            if _looks_engine_called(name):
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            raw = body.splitlines()[line_no - 1] if line_no <= len(body.splitlines()) else ""
            defs.append((cls, name, sf.rel, line_no, raw.strip()))

    if not defs:
        return unmeasured("unreal.definition_without_caller", title,
                          "Keine eigenen Methodendefinitionen gefunden.", PLATFORM)

    # Aufrufstellen NUR im Produktivcode suchen, und nur in .cpp/.inl:
    # eine Header-Zeile "float ApplyDamage(float);" ist eine DEKLARATION,
    # kein Aufruf. Wer sie mitzählt, hält jede Definition für benutzt.
    impl = [f for f in prod if f.ext in (".cpp", ".inl")]
    per_file = {f.rel: strip_comments(f.text, f.ext) for f in impl}

    findings: list[Finding] = []
    for cls, name, rel, line_no, raw in defs:
        call = re.compile(r"(?<![\w:])" + re.escape(name) + r"\s*\(")
        external = 0            # Aufrufer ausserhalb der eigenen Datei
        internal = 0            # Aufrufer in derselben Datei
        for frel, text in per_file.items():
            for m in call.finditer(text):
                start = max(0, m.start() - len(cls) - 4)
                if text[start:m.start()].rstrip().endswith(cls + "::"):
                    continue                  # das ist die Definition selbst
                if frel != rel:
                    external += 1
                    continue
                # Datei-interner Aufruf: erreichbar ist er nur, wenn die
                # AUFRUFENDE Funktion selbst erreichbar ist. Ein Engine-
                # Callback (BeginPlay, Tick, ein RPC) ist es per Definition.
                caller = _enclosing_function(text, m.start())
                bound = caller is not None and re.search(
                    r"&\s*(?:\w+::)?" + re.escape(caller) + r"\b",
                    "\n".join(per_file.values()))
                if caller is None or _looks_engine_called(caller) or bound:
                    external += 1
                else:
                    internal += 1
        # Referenz ohne Aufruf (Delegate-Bindung, Funktionszeiger) zaehlt voll.
        ref = re.compile(r"&\s*(?:\w+::)?" + re.escape(name) + r"\b")
        if any(ref.search(txt) for txt in per_file.values()):
            external += 1
        if external:
            continue
        # Nur datei-interne Aufrufer: die Fähigkeit ist nach aussen tot.
        # Das ist genau der ApplyDamage-Fall — HandleAnyDamage ruft sie,
        # aber HandleAnyDamage selbst ruft niemand aus dem Gameplay.
        if internal:
            findings.append(Finding(
                check_id="unreal.definition_without_caller",
                severity=Severity.WARNING,
                message=(f"{cls}::{name}() wird nur innerhalb von {rel} gerufen "
                         f"({internal}x) und von keiner anderen Produktivdatei. "
                         f"Die Fähigkeit ist nach aussen nicht angeschlossen."),
                file=rel, line=line_no, evidence=snippet(raw),
                fix=(f"Prüfen, ob der datei-interne Aufrufer selbst erreichbar ist. "
                     f"Wenn nicht, ist die ganze Kette tot: {name}() aus dem "
                     f"Gameplay rufen oder entfernen."),
                guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 2",
            ))
            continue
        findings.append(Finding(
            check_id="unreal.definition_without_caller",
            severity=Severity.ERROR,
            message=(f"{cls}::{name}() hat im Produktivcode keinen Aufrufer. "
                     f"Eine Definition ist Existenz — erst ein Aufrufer ist "
                     f"der Anfang von Wirkung."),
            file=rel, line=line_no, evidence=snippet(raw),
            fix=(f"Entweder {name}() an der Stelle rufen, an der die Fähigkeit "
                 f"wirken soll, oder die Definition entfernen. Ein Aufruf nur "
                 f"aus einem Test hält toten Code am Leben."),
            guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 2",
        ))
    return result_for("unreal.definition_without_caller", title, findings,
                      len(defs), "Methodendefinitionen", PLATFORM)


# ---------------------------------------------------------------------------
# § 3 — UPROPERTY(Config) ohne Leser
# ---------------------------------------------------------------------------

_CONFIG_PROP = re.compile(
    r"UPROPERTY\s*\(\s*(?=[^)]*\bConfig\b)[^)]*\)\s*"
    r"(?:\w[\w:<>,\s\*&]*?)\s+(\w+)\s*(?:=[^;]*)?;",
)

@register(
    "unreal.config_value_without_reader",
    "UPROPERTY(Config) ohne Leser — toter Balancewert",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 3",
    self_tests=[
        SelfTestCase(
            name="Config-Wert wird nirgends gelesen",
            files={"Source/DemoSettings.h": (
                "#pragma once\n"
                "UCLASS(Config=Game)\n"
                "class UDemoSettings : public UDeveloperSettings\n"
                "{\n"
                "    GENERATED_BODY()\n"
                "public:\n"
                "    UPROPERTY(Config, EditAnywhere) float RoundSeconds;\n"
                "    UPROPERTY(Config, EditAnywhere) float UnusedKnob;\n"
                "};\n"
            ),
             "Source/DemoMode.cpp": (
                "#include \"DemoSettings.h\"\n"
                "void ADemoMode::Start()\n"
                "{\n"
                "    float T = GetDefault<UDemoSettings>()->RoundSeconds;\n"
                "    StartTimer(T);\n"
                "}\n"
             )},
            expect=Status.FAIL,
            expect_finding_contains="UnusedKnob",
        ),
        SelfTestCase(
            name="Alle Config-Werte werden gelesen",
            files={"Source/DemoSettings.h": (
                "#pragma once\n"
                "UCLASS(Config=Game)\n"
                "class UDemoSettings : public UDeveloperSettings\n"
                "{\n"
                "    GENERATED_BODY()\n"
                "public:\n"
                "    UPROPERTY(Config, EditAnywhere) float RoundSeconds;\n"
                "};\n"
            ),
             "Source/DemoMode.cpp": (
                "#include \"DemoSettings.h\"\n"
                "void ADemoMode::Start()\n"
                "{\n"
                "    float T = GetDefault<UDemoSettings>()->RoundSeconds;\n"
                "    StartTimer(T);\n"
                "}\n"
             )},
            expect=Status.PASS,
        ),
    ],
)
def check_config_value_without_reader(ctx: Context) -> CheckResult:
    """Ein Wert in der .ini ohne Leser ist tot. Das Gate prüft, dass die
    Eigenschaft irgendwo GELESEN wird — nicht, dass sie deklariert ist."""
    title = "UPROPERTY(Config) ohne Leser — toter Balancewert"
    if not _is_unreal(ctx):
        return unmeasured("unreal.config_value_without_reader", title,
                          "Kein Unreal-Projekt erkannt.", PLATFORM)
    files = _sources(ctx)
    if not files:
        return unmeasured("unreal.config_value_without_reader", title,
                          "Keine C++-Quellen gefunden.", PLATFORM)

    props: list[tuple[str, str, int, str]] = []
    for sf in files:
        if _is_test_file(sf):
            continue
        body = strip_comments(sf.text, sf.ext)
        for m in _CONFIG_PROP.finditer(body):
            name = m.group(1)
            line_no = body.count("\n", 0, m.start()) + 1
            lines = body.splitlines()
            raw = lines[line_no - 1] if line_no <= len(lines) else ""
            props.append((name, sf.rel, line_no, raw.strip()))

    if not props:
        return unmeasured("unreal.config_value_without_reader", title,
                          "Keine UPROPERTY(Config)-Felder gefunden.", PLATFORM)

    # Leser dürfen überall stehen, auch in Tests — ein Test, der den Wert
    # liest, ist ein legitimer Verbraucher für diese Frage.
    all_text = "\n".join(strip_comments(f.text, f.ext) for f in files)

    findings: list[Finding] = []
    for name, rel, line_no, raw in props:
        # Nutzung = Name irgendwo, der nicht die Deklarationszeile ist.
        uses = 0
        for m in re.finditer(r"\b" + re.escape(name) + r"\b", all_text):
            ctx_start = all_text.rfind("\n", 0, m.start()) + 1
            ctx_end = all_text.find("\n", m.end())
            line = all_text[ctx_start: ctx_end if ctx_end != -1 else len(all_text)]
            if "UPROPERTY" in line:
                continue
            uses += 1
        if uses:
            continue
        findings.append(Finding(
            check_id="unreal.config_value_without_reader",
            severity=Severity.WARNING,
            message=(f"Config-Wert '{name}' wird nirgends gelesen. Ein Wert in "
                     f"der .ini ohne Leser ist tot und täuscht eine Stellschraube vor."),
            file=rel, line=line_no, evidence=snippet(raw),
            fix=(f"Entweder '{name}' an der Stelle lesen, an der er wirken soll, "
                 f"oder das Feld und seinen .ini-Eintrag entfernen."),
            guideline="CODE_QUALITY_GUIDELINES_UNREAL.md § 3",
        ))
    return result_for("unreal.config_value_without_reader", title, findings,
                      len(props), "Config-Felder", PLATFORM)


# ---------------------------------------------------------------------------
# § 7 — OnComponentHit ohne SetNotifyRigidBodyCollision
# ---------------------------------------------------------------------------

_HIT_BIND = re.compile(r"OnComponentHit\s*\.\s*(?:Add|AddDynamic|AddUniqueDynamic)\s*\(")

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


# ---------------------------------------------------------------------------
# § 8 — Zustandsschreiber ohne HasAuthority()
# ---------------------------------------------------------------------------

_REPLICATED_FIELD = re.compile(
    r"UPROPERTY\s*\(\s*(?=[^)]*\b(?:Replicated|ReplicatedUsing)\b)[^)]*\)\s*"
    r"(?:\w[\w:<>,\s\*&]*?)\s+(\w+)\s*(?:=[^;]*)?;",
)

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
