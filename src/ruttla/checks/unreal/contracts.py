"""Unreal: definitions need callers, config values need readers.

Split from the original checks/unreal.py; background and
shared helpers in _common.py.
"""

from __future__ import annotations

import re

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
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
    _CONFIG_PROP,
    _enclosing_function,
    _is_test_file,
    _is_unreal,
    _looks_engine_called,
    _METHOD_DEF,
    _sources,
    PLATFORM,
)


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
