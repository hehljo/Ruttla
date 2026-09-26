"""Apple-Checks: Xcode-Projektintegrität, Info.plist, SwiftUI-Multiplattform,
Swift-Concurrency, SwiftData/CloudKit.

Quellen: IOS_DEBUGGING_GUIDELINES.md, swiftui_multiplatform_guideline.md,
guides/swift-concurrency.md, guides/swiftdata-predicate.md,
guides/swiftui-sheets.md, guides/swiftui-viewbuilder.md, guides/widgetkit.md,
guides/ios-api-compat.md.

Gegenüber dem alten apple_gate.py korrigiert:
* Plist wird mit plistlib gelesen statt mit findall("key")/findall("string")+zip
  — das brach bei jedem <array>, <true/> oder <dict>-Wert (Schlüssel-Wert-Versatz).
* CFBundleIdentifier wird gegen die MENGE der Bundle-IDs geprüft, nicht gegen
  jede einzeln — bei Multi-Target (App + Widget + Tests) war vorher jede
  Kombination ein Fehler.
* ENABLE_HARDENED_RUNTIME und CODE_SIGN_IDENTITY werden je Build-Konfiguration
  gelesen, nicht positionell per zip gepaart.

Shared helpers and fixtures of this pack (not a rule module).
"""

from __future__ import annotations

import os
import re

from ruttla.core import Context, to_posix


PLATFORM = "apple"

# Xcode meldet "Update to recommended settings", sobald LastUpgradeCheck aelter
# ist als die installierte Toolchain. Gemessen an Xcode 27.0 (Toolchain-Stand
# September 2026, zuvor 26.4 = 2640) = 2700; die alte feste 1600 (Xcode 16.0) liess jedes aktuelle
# Projekt die Meldung zeigen, ohne dass das Gate etwas sagte.
_MIN_LAST_UPGRADE_CHECK = 2700


def _xcodeproj(ctx: Context) -> str | None:
    dirs = ctx.dirs_with_suffix(".xcodeproj")
    return sorted(dirs)[0] if dirs else None


def _pbx_text(ctx: Context) -> tuple[str, str] | None:
    proj = _xcodeproj(ctx)
    if not proj:
        return None
    pbx = os.path.join(proj, "project.pbxproj")
    if not os.path.isfile(pbx):
        return None
    try:
        with open(pbx, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), to_posix(os.path.relpath(pbx, ctx.root))
    except OSError:
        return None


# ===========================================================================
# macOS: Netzwerk-Mounts via mount_smbfs
# ===========================================================================

# Ein mount_smbfs ohne -o nobrowse registriert das Volume bei Disk Arbitration
# und der Finder zeigt es unter "Computer"/Netzwerk an — unabhängig davon, wo
# der Mountpunkt liegt. Ein eigener Ordner unter ~/Library ist KEIN Ersatz:
# die Sichtbarkeit haengt am Kernel-Flag MNT_NOBROWSE, nicht am Pfad.
# Belegt: macOS-Mount-Werkzeug für NAS-Freigaben, 18.09.2026 — Mounts unter
# ~/Library/Application Support/.../Mounts standen weiter in der
# Systemuebersicht, bis "-o", "nobrowse" in den Argumenten stand.
# Quelle: mount_smbfs(8) — "nobrowse: indicates to the Carbon subsystem
# that this volume is not to be displayed to the user".
_SMBFS_BIN = re.compile(r'mount_smbfs')
_NOBROWSE = re.compile(r'"nobrowse"|\bnobrowse\b')


def _argument_blocks(text: str) -> list[tuple[int, str]]:
    """Alle 'arguments = [...]'-Zuweisungen mit ihrem Offset im Text.

    Der Pruefbereich ist die einzelne Zuweisung, nicht die Datei: eine
    dateiweite Suche nach "nobrowse" wuerde beweisen, dass das Wort
    irgendwo vorkommt — nicht, dass jeder Mount-Aufruf es mitgibt.
    """
    out: list[tuple[int, str]] = []
    for m in re.finditer(r"\barguments\s*=\s*\[", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
            i += 1
        out.append((m.start(), text[m.end(): i - 1]))
    return out
