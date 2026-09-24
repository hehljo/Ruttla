"""Single source of truth for platforms (P01-T007).

* ``PACK_PLATFORMS`` — platforms that own an official rule pack. Only these
  are valid for ``--platform`` and ``project.platform``.
* ``PLATFORMS_WITHOUT_PACK`` — detected and reported, but no rules exist yet.
  They must never look like "measured" (R-011).

Detection measures technical PROPERTIES of the project, never folder or
project names.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context

PACK_PLATFORMS: tuple[str, ...] = (
    "universal", "apple", "web", "godot", "python", "raspberry", "unreal",
)
PLATFORMS_WITHOUT_PACK: tuple[str, ...] = ("dotnet",)
KNOWN_PLATFORMS: tuple[str, ...] = PACK_PLATFORMS + PLATFORMS_WITHOUT_PACK

# Diese Liste MUSS zu HW_IMPORT im Raspberry-Pack passen — sonst erkennt die
# Plattform ein Projekt nicht, dessen Checks dann stillschweigend gar nicht
# laufen. Belegt in der Gegenprobe: 'import serial' wurde vom Check erkannt,
# von der Plattform nicht, und ein echter Verstoß meldete grün.
RASPBERRY_HW_IMPORT = re.compile(
    r"^[ \t]*(?:import|from)\s+(RPi\.GPIO|RPi|gpiozero|smbus2?|spidev|"
    r"pigpio|serial|w1thermsensor|board|busio|adafruit_\w+|"
    r"picamera2?|luma\.\w+)\b",
    re.MULTILINE,
)

_UE_MACRO = re.compile(r"\b(?:UCLASS|USTRUCT|UENUM|GENERATED_BODY|UPROPERTY)\s*\(")


def detect_platforms(ctx: "Context") -> set[str]:
    """Erkennt Plattformen an EIGENSCHAFTEN des Projekts, nicht an Namen."""
    p: set[str] = {"universal"}
    files = ctx.all_files()
    exts = {f.ext for f in files}
    names = {f.rel.rsplit("/", 1)[-1].lower() for f in files}

    if ".swift" in exts or ctx.dirs_with_suffix(".xcodeproj"):
        p.add("apple")
    if {".ts", ".tsx", ".jsx"} & exts or "package.json" in names:
        p.add("web")
    if ".gd" in exts or "project.godot" in names:
        p.add("godot")
    if ".cs" in exts or ".csproj" in exts or ".xaml" in exts:
        p.add("dotnet")
    # Unreal: erkannt an .uproject/.uplugin, an Build.cs/Target.cs oder an
    # den UE-Reflection-Makros — nie am Ordnernamen. Ein C++-Projekt ohne
    # UCLASS/GENERATED_BODY ist kein Unreal-Projekt.
    # Diese Erkennung MUSS zu _is_unreal() im Unreal-Pack passen, sonst
    # laufen die Unreal-Checks stillschweigend gar nicht.
    if (".uproject" in exts or ".uplugin" in exts
            or any(f.rel.endswith(("Build.cs", "Target.cs")) for f in files)):
        p.add("unreal")
    elif {".cpp", ".h"} & exts:
        for f in ctx.files(".cpp", ".h"):
            if _UE_MACRO.search(f.text):
                p.add("unreal")
                break
    if ".py" in exts:
        p.add("python")
    # Raspberry: erkannt an Hardware-Bibliotheken, nicht am Verzeichnisnamen
    if "python" in p:
        for f in ctx.files(".py"):
            if RASPBERRY_HW_IMPORT.search(f.text):
                p.add("raspberry")
                break
    return p
