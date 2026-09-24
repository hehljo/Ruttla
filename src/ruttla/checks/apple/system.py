"""Apple: macOS system integration (network mounts).

Split from the original checks/apple.py; background and
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

from ._common import _argument_blocks, _NOBROWSE, _SMBFS_BIN, PLATFORM


@register(
    "apple.smb_mount_without_nobrowse",
    "mount_smbfs ohne -o nobrowse — Volume erscheint in der Systemübersicht",
    platform=PLATFORM,
    severity=Severity.ERROR,
    safe_by_default=True,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Dateisystem & Logging",
    self_tests=[
        SelfTestCase(
            name="mount_smbfs ohne nobrowse",
            files={"Sources/Core/MountExecutor.swift":
                   "import Foundation\n"
                   "func mount(_ src: String, _ mp: String) throws {\n"
                   "  let process = Process()\n"
                   "  process.executableURL = URL(fileURLWithPath: \"/sbin/mount_smbfs\")\n"
                   "  process.arguments = [src, mp]\n"
                   "  try process.run()\n"
                   "}\n"},
            expect=Status.FAIL,
            expect_finding_contains="nobrowse",
        ),
        SelfTestCase(
            name="Eigener Mountpunkt reicht nicht",
            files={"Sources/Core/MountExecutor.swift":
                   "import Foundation\n"
                   "func mount(_ src: String) throws {\n"
                   "  let mp = NSHomeDirectory() + \"/Library/Application Support/App/Mounts/Daten\"\n"
                   "  let process = Process()\n"
                   "  process.executableURL = URL(fileURLWithPath: \"/sbin/mount_smbfs\")\n"
                   "  process.arguments = [src, mp]\n"
                   "  try process.run()\n"
                   "}\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="mount_smbfs mit nobrowse",
            files={"Sources/Core/MountExecutor.swift":
                   "import Foundation\n"
                   "func mount(_ src: String, _ mp: String) throws {\n"
                   "  let process = Process()\n"
                   "  process.executableURL = URL(fileURLWithPath: \"/sbin/mount_smbfs\")\n"
                   "  process.arguments = [\"-o\", \"nobrowse\", src, mp]\n"
                   "  try process.run()\n"
                   "}\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            # Gegenrichtung zur Zuordnung: in derselben Datei steht ein
            # zweiter Prozess (umount) OHNE nobrowse. Wer dateiweit statt je
            # Zuweisung zuordnet, meldet hier faelschlich rot.
            name="Zweiter Prozess in derselben Datei ist kein Befund",
            files={"Sources/Core/MountExecutor.swift":
                   "import Foundation\n"
                   "func mount(_ src: String, _ mp: String) throws {\n"
                   "  let process = Process()\n"
                   "  process.executableURL = URL(fileURLWithPath: \"/sbin/mount_smbfs\")\n"
                   "  process.arguments = [\"-o\", \"nobrowse\", src, mp]\n"
                   "  try process.run()\n"
                   "}\n"
                   "func unmount(_ mp: String) throws {\n"
                   "  let process = Process()\n"
                   "  process.executableURL = URL(fileURLWithPath: \"/sbin/umount\")\n"
                   "  process.arguments = [\"-f\", mp]\n"
                   "  try process.run()\n"
                   "}\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_smb_nobrowse(ctx: Context) -> CheckResult:
    """Gemessen wird die Eigenschaft 'dieser mount_smbfs-Aufruf gibt nobrowse
    mit', nicht der Mountpfad. Der Pfad ist eine Bauform-Annahme: die
    Sichtbarkeit entscheidet Disk Arbitration am Kernel-Flag, nicht am Ort."""
    title = "mount_smbfs ohne -o nobrowse — Volume erscheint in der Systemübersicht"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.smb_mount_without_nobrowse", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)

    callers = 0
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        if not _SMBFS_BIN.search(body):
            continue
        for start, block in _argument_blocks(body):
            # Die Zuweisung gehoert zu einem mount_smbfs-Prozess, wenn der
            # Binaername im selben Funktionsrumpf davor steht. Gemessen am
            # naechstgelegenen Vorkommen, nicht dateiweit.
            before = body[:start]
            smb_pos = before.rfind("mount_smbfs")
            if smb_pos < 0:
                continue
            # Zwischen Binaerzuweisung und Argumentliste darf keine andere
            # executableURL-Zuweisung liegen — sonst gehoert der Block zu
            # einem anderen Prozess.
            if re.search(r"executableURL\s*=", before[smb_pos:]):
                continue
            callers += 1
            if _NOBROWSE.search(block):
                continue
            line_no = body.count("\n", 0, start) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="apple.smb_mount_without_nobrowse",
                severity=Severity.ERROR,
                message="mount_smbfs ohne '-o nobrowse': macOS registriert das "
                        "Volume bei Disk Arbitration, der Finder zeigt es unter "
                        "'Computer' an — auch wenn der Mountpunkt in einem "
                        "eigenen Ordner liegt.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix='Als erste Argumente "-o", "nobrowse" mitgeben: '
                    'process.arguments = ["-o", "nobrowse", smbSource, mountPoint]. '
                    "Belegt in mount_smbfs(8): nobrowse blendet das Volume für "
                    "Finder/Carbon aus. Zugriff bleibt über Symlinks möglich.",
                guideline="IOS_DEBUGGING_GUIDELINES.md",
            ))
    if not callers:
        return unmeasured("apple.smb_mount_without_nobrowse", title,
                          "Kein mount_smbfs-Aufruf im Projekt.", PLATFORM)
    return result_for("apple.smb_mount_without_nobrowse", title, findings,
                      callers, "mount_smbfs-Aufrufe", PLATFORM)
