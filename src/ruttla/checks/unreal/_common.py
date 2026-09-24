"""Unreal-Engine-Checks aus CODE_QUALITY_GUIDELINES_UNREAL.md.

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

Shared helpers and fixtures of this pack (not a rule module).
"""

from __future__ import annotations

import os
import re

from ruttla.core import Context


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


# ---------------------------------------------------------------------------
# § 3 — UPROPERTY(Config) ohne Leser
# ---------------------------------------------------------------------------

_CONFIG_PROP = re.compile(
    r"UPROPERTY\s*\(\s*(?=[^)]*\bConfig\b)[^)]*\)\s*"
    r"(?:\w[\w:<>,\s\*&]*?)\s+(\w+)\s*(?:=[^;]*)?;",
)


# ---------------------------------------------------------------------------
# § 7 — OnComponentHit ohne SetNotifyRigidBodyCollision
# ---------------------------------------------------------------------------

_HIT_BIND = re.compile(r"OnComponentHit\s*\.\s*(?:Add|AddDynamic|AddUniqueDynamic)\s*\(")


# ---------------------------------------------------------------------------
# § 8 — Zustandsschreiber ohne HasAuthority()
# ---------------------------------------------------------------------------

_REPLICATED_FIELD = re.compile(
    r"UPROPERTY\s*\(\s*(?=[^)]*\b(?:Replicated|ReplicatedUsing)\b)[^)]*\)\s*"
    r"(?:\w[\w:<>,\s\*&]*?)\s+(\w+)\s*(?:=[^;]*)?;",
)
