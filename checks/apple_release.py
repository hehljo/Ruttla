#!/usr/bin/env python3
"""Offline-Prüfungen für reproduzierbare Apple-Releases.

Bewusst konservativ: Das Modul parst veröffentlichte Dateiformate und
Xcode-erzeugte Shared Schemes, löst aber keine Target-Build-Settings per Regex
auf. Bei unbekannten Referenzformen wird UNMEASURED statt PASS/FAIL geliefert.
PBXFileSystemSynchronizedRootGroup ändert weder Scheme-Target-IDs noch die
Syntax der hier geprüften Metadaten und wird deshalb ohne Sonderannahmen
unterstützt.

Offizielle Apple-Referenzen (am 2026-07-10 read-only geprüft):
* https://developer.apple.com/documentation/xcode/customizing-the-build-schemes-for-a-project
* https://developer.apple.com/documentation/xcode/localizing-and-varying-text-with-a-string-catalog
* https://developer.apple.com/library/archive/documentation/Xcode/Reference/xcode_ref-Asset_Catalog_Format/
* https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Introduction/Introduction.html
"""

from __future__ import annotations

import fnmatch
import json
import os
import plistlib
import re
import urllib.parse
import xml.etree.ElementTree as ET

from core import (
    DEFAULT_EXCLUDE_DIRS,
    CheckResult,
    Context,
    Finding,
    SelfTestCase,
    Severity,
    Status,
    failed,
    ok,
    register,
    result_for,
    unmeasured,
)

PLATFORM = "apple"

_HEALTHY_PROJECT = """// !$*UTF8*$!
objects = {
/* Begin PBXNativeTarget section */
AAA111 /* App */ = {
    isa = PBXNativeTarget;
    name = App;
};
/* End PBXNativeTarget section */
/* Begin XCBuildConfiguration section */
BBB111 /* Debug */ = {
    isa = XCBuildConfiguration;
    buildSettings = {};
    name = Debug;
};
BBB222 /* Release */ = {
    isa = XCBuildConfiguration;
    buildSettings = {};
    name = Release;
};
/* End XCBuildConfiguration section */
};
"""

_HEALTHY_SCHEME = """<?xml version="1.0" encoding="UTF-8"?>
<Scheme version="1.7">
  <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES">
    <BuildActionEntries>
      <BuildActionEntry buildForTesting="YES" buildForRunning="YES"
        buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">
        <BuildableReference BuildableIdentifier="primary"
          BlueprintIdentifier="AAA111" BuildableName="App.app"
          BlueprintName="App" ReferencedContainer="container:P.xcodeproj"/>
      </BuildActionEntry>
    </BuildActionEntries>
  </BuildAction>
  <LaunchAction buildConfiguration="Debug">
    <BuildableProductRunnable>
      <BuildableReference BuildableIdentifier="primary"
        BlueprintIdentifier="AAA111" BuildableName="App.app"
        BlueprintName="App" ReferencedContainer="container:P.xcodeproj"/>
    </BuildableProductRunnable>
  </LaunchAction>
  <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
"""

_HEALTHY_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
  <key>CFBundleDocumentTypes</key><array><dict><key>CFBundleTypeName</key><string>Document</string></dict></array>
</dict></plist>
"""

_HEALTHY_XCSTRINGS = '{"sourceLanguage":"en","strings":{},"version":"1.0"}\n'
_HEALTHY_CONTENTS = '{"info":{"author":"xcode","version":1}}\n'


def _walk_files(ctx: Context) -> list[tuple[str, str]]:
    """Dateien inklusive Asset-Katalogen, mit denselben Ausschlüssen wie core."""
    found: list[tuple[str, str]] = []
    excluded_dirs = DEFAULT_EXCLUDE_DIRS | set(ctx.config.exclude_dirs)
    for dirpath, dirnames, filenames in os.walk(ctx.root):
        dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ctx.root)
            if any(fnmatch.fnmatch(rel, pattern)
                   for pattern in ctx.config.exclude_globs):
                continue
            try:
                if os.path.getsize(path) > ctx.config.max_file_bytes:
                    continue
            except OSError:
                continue
            found.append((path, rel))
    return found


def _project_dirs(ctx: Context) -> list[str]:
    projects: set[str] = set()
    excluded_dirs = DEFAULT_EXCLUDE_DIRS | set(ctx.config.exclude_dirs)
    for dirpath, dirnames, _ in os.walk(ctx.root):
        dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
        for dirname in dirnames:
            if not dirname.endswith(".xcodeproj"):
                continue
            path = os.path.join(dirpath, dirname)
            rel = os.path.relpath(path, ctx.root)
            if not any(fnmatch.fnmatch(rel, pattern)
                       for pattern in ctx.config.exclude_globs):
                projects.add(path)
    return sorted(projects)


def _shared_schemes(ctx: Context) -> list[tuple[str, str]]:
    schemes: list[tuple[str, str]] = []
    for path, rel in _walk_files(ctx):
        parts = rel.replace(os.sep, "/").split("/")
        if (path.endswith(".xcscheme")
                and any(parts[i:i + 2] == ["xcshareddata", "xcschemes"]
                        for i in range(max(0, len(parts) - 1)))):
            schemes.append((path, rel))
    return sorted(schemes, key=lambda item: item[1])


def _xml_root(path: str) -> ET.Element | None:
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _elements(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if _local_tag(element) == name]


def _scheme_container_base(scheme_path: str) -> str | None:
    current = os.path.dirname(scheme_path)
    while current != os.path.dirname(current):
        if current.endswith((".xcodeproj", ".xcworkspace")):
            return os.path.dirname(current)
        current = os.path.dirname(current)
    return None


def _referenced_project(scheme_path: str, raw: str) -> str | None:
    if not raw.startswith("container:"):
        return None
    reference = urllib.parse.unquote(raw[len("container:"):])
    if not reference:
        return None
    base = _scheme_container_base(scheme_path)
    if base is None:
        return None
    path = reference if os.path.isabs(reference) else os.path.join(base, reference)
    path = os.path.normpath(path)
    return path if path.endswith(".xcodeproj") else None


def _pbx_section(text: str, isa: str) -> str | None:
    begin = f"/* Begin {isa} section */"
    end = f"/* End {isa} section */"
    start = text.find(begin)
    if start < 0:
        return None
    stop = text.find(end, start + len(begin))
    if stop < 0:
        return None
    return text[start + len(begin):stop]


def _brace_delta(line: str) -> int:
    """Zählt PBX-Klammern außerhalb von Strings und Blockkommentaren."""
    delta = 0
    index = 0
    in_string = False
    while index < len(line):
        char = line[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if line.startswith("/*", index):
            stop = line.find("*/", index + 2)
            if stop < 0:
                break
            index = stop + 2
            continue
        if char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
        index += 1
    return delta


def _target_ids(text: str) -> set[str] | None:
    """Liest PBX-Objekte anhand ihrer ISA, ohne Target-Settings aufzulösen.

    Manche gültigen Projekte (belegt an einer realen macOS-App) besitzen vor der ersten
    PBXNativeTarget-Deklaration keinen Begin-Sektionskommentar. Kommentare sind
    daher kein Vertrag; maßgeblich sind nur Top-Level-Objekte unter `objects`.
    """
    objects_match = re.search(r"^\s*objects\s*=\s*\{", text, re.MULTILINE)
    if not objects_match:
        return None
    lines = text[objects_match.end():].splitlines()
    object_start = re.compile(
        r"^\s*([A-Za-z0-9_]+)(?:\s+/\*.*?\*/)?\s*=\s*\{"
    )
    isa_pattern = re.compile(
        r"\bisa\s*=\s*(PBXNativeTarget|PBXAggregateTarget|PBXLegacyTarget)\s*;"
    )
    ids: set[str] = set()
    objects_depth = 1
    current_id: str | None = None
    current_is_target = False
    saw_object = False
    for line in lines:
        if objects_depth == 1 and current_id is None:
            match = object_start.match(line)
            if match:
                current_id = match.group(1)
                current_is_target = bool(isa_pattern.search(line))
                saw_object = True
        elif current_id is not None and isa_pattern.search(line):
            current_is_target = True
        objects_depth += _brace_delta(line)
        if current_id is not None and objects_depth == 1:
            if current_is_target:
                ids.add(current_id)
            current_id = None
            current_is_target = False
        if objects_depth <= 0:
            break
    return ids if saw_object else None


def _configuration_names(text: str) -> set[str] | None:
    """Liest nur Namen aller XCBuildConfiguration-Objekte im Projekt.

    Das ist absichtlich eine einseitige Prüfung: Fehlt ein ArchiveAction-Name
    projektweit, ist er sicher ungültig. Sein bloßes Vorkommen beweist dagegen
    nicht, dass er dem archivierten Target zugeordnet ist.
    """
    section = _pbx_section(text, "XCBuildConfiguration")
    if section is None:
        return None
    names: set[str] = set()
    object_start = re.compile(r"^\s*[A-Za-z0-9_]+(?:\s+/\*.*?\*/)?\s*=\s*\{")
    name_line = re.compile(r"^\s*name\s*=\s*(.+?)\s*;\s*$")
    depth = 0
    in_object = False
    for line in section.splitlines():
        if not in_object and object_start.match(line):
            in_object = True
            depth = line.count("{") - line.count("}")
            continue
        if not in_object:
            continue
        if depth == 1:
            match = name_line.match(line)
            if match:
                names.add(match.group(1).strip().strip('"'))
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            in_object = False
            depth = 0
    return names


def _read_project(path: str) -> str | None:
    pbx = os.path.join(path, "project.pbxproj")
    try:
        with open(pbx, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


# --------------------------------------------------------------------------
# Build-Settings je Target-Konfiguration
#
# Die Checks darunter messen App-Store-Pflichtangaben. Der Prüfbereich ist
# dabei die einzelne Target-Konfiguration, nicht die Projektdatei: ein
# dateiweites re.search findet den Schlüssel in irgendeinem Target (Tests,
# Helper, Extension) und meldet grün, während das App-Target ihn nicht trägt.
#
# Belegt am 2026-09-22 (macOS-App, Bundle-ID anonymisiert): DEVELOPMENT_TEAM war im
# App-Target leer, `apple.project_settings` blieb trotzdem grün, weil sein
# re.search über die ganze Datei lief. Apple lehnte den Upload erst in
# App Store Connect ab.
# --------------------------------------------------------------------------

# Nur Konfigurationen dieser Produkttypen tragen App-Store-Pflichtangaben.
# Testbundles, Helper und Extensions sind ausdrücklich ausgenommen: sie
# brauchen weder App-Kategorie noch eigenen Anzeigenamen.
_APPLICATION_PRODUCT_TYPE = "com.apple.product-type.application"


def _balanced_block(text: str, open_index: int) -> tuple[str, int] | None:
    """Schneidet den Block ab `{` bis zur zugehörigen `}` heraus."""
    depth = 0
    index = open_index
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if text.startswith("/*", index):
            stop = text.find("*/", index + 2)
            if stop < 0:
                return None
            index = stop + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1:index], index + 1
        index += 1
    return None


def _pbx_objects(text: str, isa: str) -> list[tuple[str, str]]:
    """Liefert (Objekt-ID, Objektrumpf) je Top-Level-Objekt mit dieser ISA.

    Ankert an der ISA im Objektrumpf, nicht an den Begin/End-Sektions-
    kommentaren: die fehlen in Xcode-generierten Projekten teilweise (belegt
    an einer realen macOS-App) und sind deshalb kein Vertrag.
    """
    objects_match = re.search(r"^\s*objects\s*=\s*\{", text, re.MULTILINE)
    if not objects_match:
        return []
    body = _balanced_block(text, objects_match.end() - 1)
    if body is None:
        return []
    objects_body = body[0]
    results: list[tuple[str, str]] = []
    object_start = re.compile(
        r"^[ \t]*([A-Za-z0-9_]+)(?:\s*/\*.*?\*/)?\s*=\s*\{", re.MULTILINE
    )
    position = 0
    while True:
        match = object_start.search(objects_body, position)
        if not match:
            break
        block = _balanced_block(objects_body, match.end() - 1)
        if block is None:
            break
        inner, end_index = block
        if re.search(rf"\bisa\s*=\s*{re.escape(isa)}\s*;", inner):
            results.append((match.group(1), inner))
        position = end_index
    return results


def _setting(block: str, key: str) -> str | None:
    """Liest einen Build-Setting-Wert; None wenn der Schlüssel fehlt.

    Ein leerer Wert (`DEVELOPMENT_TEAM = "";`) kommt als leerer String zurück
    und ist damit unterscheidbar von 'Schlüssel nicht vorhanden' — genau die
    Unterscheidung, an der der reale Signing-Fehler hing.
    """
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*(.*?);\s*$",
                      block, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip().strip('"')


def _application_configurations(text: str) -> list[dict]:
    """Alle Build-Konfigurationen, die zu einem App-Target gehören.

    Gemessen wird die Eigenschaft 'ist eine Anwendung', nicht ein Zielname:
    productType statt Namenskonvention. Targets ohne aufloesbare
    Konfigurationsliste werden als `resolved=False` gemeldet, damit der
    aufrufende Check UNMEASURED statt PASS liefern kann.
    """
    config_blocks = {obj_id: block
                     for obj_id, block in _pbx_objects(text, "XCBuildConfiguration")}
    config_lists: dict[str, list[str]] = {}
    for list_id, block in _pbx_objects(text, "XCConfigurationList"):
        ids: list[str] = []
        children = re.search(r"buildConfigurations\s*=\s*\(", block)
        if children:
            closing = block.find(")", children.end())
            if closing > 0:
                for entry in block[children.end():closing].split(","):
                    entry = entry.split("/*")[0].strip()
                    if entry:
                        ids.append(entry)
        config_lists[list_id] = ids

    results: list[dict] = []
    for target_id, target_block in _pbx_objects(text, "PBXNativeTarget"):
        product_type = _setting(target_block, "productType")
        if product_type != _APPLICATION_PRODUCT_TYPE:
            continue
        target_name = _setting(target_block, "name") or target_id
        list_id = _setting(target_block, "buildConfigurationList")
        if list_id:
            list_id = list_id.split("/*")[0].strip()
        config_ids = config_lists.get(list_id or "", [])
        if not config_ids:
            results.append({"target": target_name, "config": None,
                            "block": "", "resolved": False})
            continue
        for config_id in config_ids:
            block = config_blocks.get(config_id)
            if block is None:
                results.append({"target": target_name, "config": None,
                                "block": "", "resolved": False})
                continue
            results.append({
                "target": target_name,
                "config": _setting(block, "name") or config_id,
                "block": block,
                "resolved": True,
            })
    return results


def _builds_for_macos(text: str) -> bool:
    """Ob das Projekt für macOS baut.

    Gemessen wird die Eigenschaft über ALLE Build-Konfigurationen, nicht nur
    über die des Targets: Xcode legt SDKROOT und das Deployment Target
    üblicherweise auf Projektebene ab, das Target erbt sie. Eine Erkennung,
    die nur in der Target-Konfiguration nachsieht, hält ein echtes
    macOS-Projekt für plattformlos (belegt an einer realen macOS-App, 2026-09-22 — der
    Sandbox-Check meldete dadurch UNMEASURED statt des vorhandenen Fehlers).

    Maßgeblich ist das SDK, gegen das gebaut wird, NICHT das bloße
    Vorhandensein eines MACOSX_DEPLOYMENT_TARGET. Belegt am 2026-09-22
    an einer realen iOS-App: ein reines iOS-Projekt (SDKROOT = iphoneos) trägt
    MACOSX_DEPLOYMENT_TARGET = 14.0 als Beiwerk von Mac Catalyst
    beziehungsweise 'Designed for iPad'. Wer darauf anspringt, meldet für
    jede iOS-App eine fehlende Mac-Sandbox — ein falsch-positives hartes
    Gate, und das ist schlimmer als gar keins.
    """
    builds_for_ios = False
    macos_claimed = False
    for _config_id, block in _pbx_objects(text, "XCBuildConfiguration"):
        sdk = (_setting(block, "SDKROOT") or "").lower()
        if "macos" in sdk:
            return True
        if "iphone" in sdk or "appletv" in sdk or "watch" in sdk:
            builds_for_ios = True
        supported = (_setting(block, "SUPPORTED_PLATFORMS") or "").lower()
        if "macos" in supported:
            macos_claimed = True
    return macos_claimed and not builds_for_ios


def _app_target_projects(ctx: Context) -> list[tuple[str, str, list[dict]]]:
    """(Projektpfad, relativer Pfad, App-Konfigurationen) je .xcodeproj."""
    results: list[tuple[str, str, list[dict]]] = []
    for project in _project_dirs(ctx):
        text = _read_project(project)
        if text is None:
            continue
        rel = os.path.relpath(os.path.join(project, "project.pbxproj"), ctx.root)
        configs = _application_configurations(text)
        macos = _builds_for_macos(text)
        for config in configs:
            config["macos"] = macos
        results.append((project, rel, configs))
    return results


@register(
    "apple.release.shared_scheme_present",
    "Kein eingechecktes Shared Scheme",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Buildort & Toolchain",
    self_tests=[
        SelfTestCase(
            name="gesund: Shared Scheme vorhanden",
            files={"P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                   "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme": _HEALTHY_SCHEME},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: nur lokales Projekt ohne Shared Scheme",
            files={"P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT},
            expect=Status.FAIL,
        ),
    ],
)
def check_shared_scheme_present(ctx: Context) -> CheckResult:
    title = "Kein eingechecktes Shared Scheme"
    projects = _project_dirs(ctx)
    if not projects:
        return unmeasured("apple.release.shared_scheme_present", title,
                          "Kein .xcodeproj gefunden.", PLATFORM)
    schemes = _shared_schemes(ctx)
    if schemes:
        return ok("apple.release.shared_scheme_present", title, 1,
                  "Apple-Projekte", PLATFORM)
    finding = Finding(
        check_id="apple.release.shared_scheme_present",
        severity=Severity.WARNING,
        message="Kein Scheme unter xcshareddata/xcschemes eingecheckt.",
        file=os.path.relpath(projects[0], ctx.root),
        fix="Das Release-Scheme in Xcode als Shared markieren und einchecken.",
        guideline="IOS_DEBUGGING_GUIDELINES.md § Buildort & Toolchain",
    )
    return failed("apple.release.shared_scheme_present", title, [finding],
                  1, "Apple-Projekte", PLATFORM)


@register(
    "apple.release.shared_scheme_xml",
    "Shared Scheme ist kein gültiges Xcode-Scheme-XML",
    platform=PLATFORM,
    severity=Severity.ERROR,
    safe_by_default=True,
    guideline="Apple: Customizing the build schemes for a project",
    self_tests=[
        SelfTestCase(
            name="gesund: wohlgeformtes Scheme",
            files={"P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                   "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme": _HEALTHY_SCHEME},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: nicht wohlgeformtes XML",
            files={"P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                   "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme": "<Scheme><BuildAction></Scheme>\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="negativ: falsches Wurzelelement",
            files={"P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                   "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme": "<?xml version=\"1.0\"?><Workspace/>\n"},
            expect=Status.FAIL,
        ),
    ],
)
def check_shared_scheme_xml(ctx: Context) -> CheckResult:
    title = "Shared Scheme ist kein gültiges Xcode-Scheme-XML"
    schemes = _shared_schemes(ctx)
    if not schemes:
        return unmeasured("apple.release.shared_scheme_xml", title,
                          "Kein Shared Scheme gefunden.", PLATFORM)
    findings: list[Finding] = []
    for path, rel in schemes:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            line = exc.position[0] if getattr(exc, "position", None) else None
            findings.append(Finding(
                check_id="apple.release.shared_scheme_xml",
                severity=Severity.ERROR,
                message=f"Shared Scheme ist kein wohlgeformtes XML: {exc}.",
                file=rel,
                line=line,
                fix="Scheme in Xcode neu speichern und die XML-Konfliktmarker oder Syntaxfehler entfernen.",
            ))
            continue
        except OSError as exc:
            findings.append(Finding(
                check_id="apple.release.shared_scheme_xml",
                severity=Severity.ERROR,
                message=f"Shared Scheme ist nicht lesbar: {exc}.",
                file=rel,
                fix="Dateirechte und Checkout prüfen.",
            ))
            continue
        if _local_tag(root) != "Scheme":
            findings.append(Finding(
                check_id="apple.release.shared_scheme_xml",
                severity=Severity.ERROR,
                message=f"Wurzelelement ist '{_local_tag(root)}' statt 'Scheme'.",
                file=rel,
                fix="Eine von Xcode erzeugte .xcscheme-Datei einchecken.",
            ))
    return result_for("apple.release.shared_scheme_xml", title, findings,
                      len(schemes), "Shared Schemes", PLATFORM)


@register(
    "apple.release.scheme_target_reference",
    "Shared Scheme verweist nicht auf ein vorhandenes Projekt-Target",
    platform=PLATFORM,
    severity=Severity.ERROR,
    safe_by_default=True,
    guideline="Apple: Customizing the build schemes for a project",
    self_tests=[
        SelfTestCase(
            name="gesund: Target-ID existiert",
            files={"P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                   "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme": _HEALTHY_SCHEME},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: synchronisierte Gruppe ändert Target-Referenz nicht",
            files={
                "P.xcodeproj/project.pbxproj": (
                    _HEALTHY_PROJECT
                    + "\n/* Begin PBXFileSystemSynchronizedRootGroup section */\n"
                    + "SYNC1 = { isa = PBXFileSystemSynchronizedRootGroup; path = App; sourceTree = \"<group>\"; };\n"
                    + "/* End PBXFileSystemSynchronizedRootGroup section */\n"
                ),
                "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme": _HEALTHY_SCHEME,
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: Target ohne Sektionskommentar",
            files={
                "P.xcodeproj/project.pbxproj": (
                    "// !$*UTF8*$!\nobjects = {\n"
                    "AAA111 = { isa = PBXNativeTarget; name = App; };\n"
                    "};\n"
                ),
                "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme": _HEALTHY_SCHEME,
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: BlueprintIdentifier fehlt im Projekt",
            files={
                "P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme":
                    _HEALTHY_SCHEME.replace("AAA111", "MISSING_TARGET"),
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="negativ: referenziertes Projekt fehlt",
            files={
                "P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme":
                    _HEALTHY_SCHEME.replace("container:P.xcodeproj", "container:Missing.xcodeproj"),
            },
            expect=Status.FAIL,
        ),
    ],
)
def check_scheme_target_reference(ctx: Context) -> CheckResult:
    title = "Shared Scheme verweist nicht auf ein vorhandenes Projekt-Target"
    schemes = _shared_schemes(ctx)
    if not schemes:
        return unmeasured("apple.release.scheme_target_reference", title,
                          "Kein Shared Scheme gefunden.", PLATFORM)
    findings: list[Finding] = []
    unknown = 0
    valid_schemes = 0
    for path, rel in schemes:
        root = _xml_root(path)
        if root is None or _local_tag(root) != "Scheme":
            unknown += 1
            continue
        valid_schemes += 1
        references = _elements(root, "BuildableReference")
        if not references:
            findings.append(Finding(
                check_id="apple.release.scheme_target_reference",
                severity=Severity.ERROR,
                message="Shared Scheme enthält keine BuildableReference.",
                file=rel,
                fix="Das zu bauende Target im Scheme ergänzen.",
            ))
            continue
        for reference in references:
            blueprint = reference.get("BlueprintIdentifier", "").strip()
            container = reference.get("ReferencedContainer", "").strip()
            if not blueprint or not container:
                findings.append(Finding(
                    check_id="apple.release.scheme_target_reference",
                    severity=Severity.ERROR,
                    message="BuildableReference hat keine vollständige Blueprint-/Container-Referenz.",
                    file=rel,
                    fix="Die BuildableReference von Xcode neu erzeugen lassen.",
                ))
                continue
            project = _referenced_project(path, container)
            if project is None:
                unknown += 1
                continue
            project_text = _read_project(project)
            if project_text is None:
                findings.append(Finding(
                    check_id="apple.release.scheme_target_reference",
                    severity=Severity.ERROR,
                    message=f"Referenziertes Projekt fehlt oder ist nicht lesbar: {container}.",
                    file=rel,
                    fix="ReferencedContainer auf ein vorhandenes .xcodeproj korrigieren.",
                ))
                continue
            target_ids = _target_ids(project_text)
            if target_ids is None:
                unknown += 1
                continue
            if blueprint not in target_ids:
                findings.append(Finding(
                    check_id="apple.release.scheme_target_reference",
                    severity=Severity.ERROR,
                    message=f"BlueprintIdentifier '{blueprint}' ist kein Target in {container}.",
                    file=rel,
                    fix="Scheme in Xcode neu mit dem vorhandenen Target verknüpfen.",
                ))
    if findings:
        return failed("apple.release.scheme_target_reference", title, findings,
                      max(valid_schemes, 1), "Shared Schemes", PLATFORM)
    if unknown:
        return unmeasured(
            "apple.release.scheme_target_reference", title,
            f"{unknown} Scheme-/Container-Referenz(en) konnten ohne Xcode nicht sicher aufgelöst werden.",
            PLATFORM,
        )
    return ok("apple.release.scheme_target_reference", title, valid_schemes,
              "Shared Schemes", PLATFORM)


@register(
    "apple.release.archive_action",
    "Shared Scheme ist nicht konsistent für Archive konfiguriert",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple: Customizing the build schemes for a project",
    self_tests=[
        SelfTestCase(
            name="gesund: Release-Archiv und archiviertes Buildable",
            files={"P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                   "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme": _HEALTHY_SCHEME},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: ArchiveAction fehlt",
            files={
                "P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme":
                    _HEALTHY_SCHEME.replace(
                        '  <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>\n', ""),
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="negativ: unbekannte Archiv-Konfiguration",
            files={
                "P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme":
                    _HEALTHY_SCHEME.replace('buildConfiguration="Release"',
                                            'buildConfiguration="Distribution"'),
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="negativ: kein Buildable fürs Archiv aktiviert",
            files={
                "P.xcodeproj/project.pbxproj": _HEALTHY_PROJECT,
                "P.xcodeproj/xcshareddata/xcschemes/App.xcscheme":
                    _HEALTHY_SCHEME.replace('buildForArchiving="YES"',
                                            'buildForArchiving="NO"'),
            },
            expect=Status.FAIL,
        ),
    ],
)
def check_archive_action(ctx: Context) -> CheckResult:
    title = "Shared Scheme ist nicht konsistent für Archive konfiguriert"
    schemes = _shared_schemes(ctx)
    if not schemes:
        return unmeasured("apple.release.archive_action", title,
                          "Kein Shared Scheme gefunden.", PLATFORM)
    findings: list[Finding] = []
    unknown = 0
    valid_schemes = 0
    for path, rel in schemes:
        root = _xml_root(path)
        if root is None or _local_tag(root) != "Scheme":
            unknown += 1
            continue
        valid_schemes += 1
        archive_actions = _elements(root, "ArchiveAction")
        if len(archive_actions) != 1:
            findings.append(Finding(
                check_id="apple.release.archive_action",
                severity=Severity.ERROR,
                message=f"Erwartet genau eine ArchiveAction, gefunden: {len(archive_actions)}.",
                file=rel,
                fix="Archive-Aktion im Scheme-Editor neu konfigurieren.",
            ))
            continue
        archive = archive_actions[0]
        configuration = archive.get("buildConfiguration", "").strip()
        if not configuration:
            findings.append(Finding(
                check_id="apple.release.archive_action",
                severity=Severity.ERROR,
                message="ArchiveAction hat keine buildConfiguration.",
                file=rel,
                fix="Eine vorhandene Archiv-Build-Konfiguration auswählen.",
            ))
        archive_entries = [entry for entry in _elements(root, "BuildActionEntry")
                           if entry.get("buildForArchiving") == "YES"]
        if not archive_entries:
            findings.append(Finding(
                check_id="apple.release.archive_action",
                severity=Severity.ERROR,
                message="Kein BuildActionEntry ist für Archiving aktiviert.",
                file=rel,
                fix="Beim Release-Buildable die Archive-Aktion aktivieren.",
            ))

        project_paths: set[str] = set()
        for reference in _elements(root, "BuildableReference"):
            project = _referenced_project(
                path, reference.get("ReferencedContainer", "").strip())
            if project is not None:
                project_paths.add(project)
        known_configurations: set[str] = set()
        parsed_project = False
        for project in project_paths:
            project_text = _read_project(project)
            if project_text is None:
                continue
            names = _configuration_names(project_text)
            if names is not None:
                parsed_project = True
                known_configurations |= names
        if configuration:
            if not parsed_project:
                unknown += 1
            elif configuration not in known_configurations:
                findings.append(Finding(
                    check_id="apple.release.archive_action",
                    severity=Severity.ERROR,
                    message=(f"Archiv-Konfiguration '{configuration}' kommt in keinem "
                             "referenzierten Projekt vor."),
                    file=rel,
                    fix="ArchiveAction auf einen vorhandenen XCBuildConfiguration-Namen setzen.",
                ))
    if findings:
        return failed("apple.release.archive_action", title, findings,
                      max(valid_schemes, 1), "Shared Schemes", PLATFORM)
    if unknown:
        return unmeasured(
            "apple.release.archive_action", title,
            f"{unknown} Scheme-/Projektteil(e) konnten offline nicht sicher validiert werden.",
            PLATFORM,
        )
    return ok("apple.release.archive_action", title, valid_schemes,
              "Shared Schemes", PLATFORM)


@register(
    "apple.release.plist_syntax",
    "Apple-Property-List ist nicht lesbar",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple: About Info.plist Keys and Values",
    self_tests=[
        SelfTestCase(
            name="gesund: verschachtelte Property List",
            files={"App/Info.plist": _HEALTHY_PLIST},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: beschädigte Property List",
            files={"App/Info.plist": "<?xml version=\"1.0\"?><plist><dict><key>Name</key><string>x</dict></plist>\n"},
            expect=Status.FAIL,
        ),
    ],
)
def check_plist_syntax(ctx: Context) -> CheckResult:
    title = "Apple-Property-List ist nicht lesbar"
    candidates = [(path, rel) for path, rel in _walk_files(ctx)
                  if rel.endswith((".plist", ".entitlements", ".xcprivacy"))]
    if not candidates:
        return unmeasured("apple.release.plist_syntax", title,
                          "Keine Property-List-Datei gefunden.", PLATFORM)
    findings: list[Finding] = []
    for path, rel in candidates:
        try:
            with open(path, "rb") as handle:
                plistlib.load(handle)
        except Exception as exc:
            findings.append(Finding(
                check_id="apple.release.plist_syntax",
                severity=Severity.ERROR,
                message=f"Property List kann nicht gelesen werden ({type(exc).__name__}).",
                file=rel,
                fix="Datei als gültige XML- oder Binär-Property-List neu speichern.",
            ))
    return result_for("apple.release.plist_syntax", title, findings,
                      len(candidates), "Property-List-Dateien", PLATFORM)


@register(
    "apple.release.xcstrings_json",
    "String Catalog enthält ungültiges JSON",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple: Localizing and varying text with a string catalog",
    self_tests=[
        SelfTestCase(
            name="gesund: gültiger String Catalog",
            files={"App/Localizable.xcstrings": _HEALTHY_XCSTRINGS},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: JSON mit nachlaufendem Komma",
            files={"App/Localizable.xcstrings": '{"sourceLanguage":"en","strings":{},}\n'},
            expect=Status.FAIL,
        ),
    ],
)
def check_xcstrings_json(ctx: Context) -> CheckResult:
    title = "String Catalog enthält ungültiges JSON"
    candidates = [(path, rel) for path, rel in _walk_files(ctx)
                  if rel.endswith(".xcstrings")]
    if not candidates:
        return unmeasured("apple.release.xcstrings_json", title,
                          "Kein .xcstrings-Katalog gefunden.", PLATFORM)
    findings: list[Finding] = []
    for path, rel in candidates:
        try:
            with open(path, "rb") as handle:
                json.load(handle)
        except json.JSONDecodeError as exc:
            findings.append(Finding(
                check_id="apple.release.xcstrings_json",
                severity=Severity.ERROR,
                message=f"String Catalog ist kein gültiges JSON: {exc.msg}.",
                file=rel,
                line=exc.lineno,
                fix="JSON-Syntax korrigieren oder den Katalog in Xcode neu speichern.",
            ))
        except (OSError, UnicodeError) as exc:
            findings.append(Finding(
                check_id="apple.release.xcstrings_json",
                severity=Severity.ERROR,
                message=f"String Catalog ist nicht lesbar ({type(exc).__name__}).",
                file=rel,
                fix="Kodierung, Dateirechte und Checkout prüfen.",
            ))
    return result_for("apple.release.xcstrings_json", title, findings,
                      len(candidates), "String-Kataloge", PLATFORM)


@register(
    "apple.release.asset_contents_json",
    "Asset-Catalog Contents.json enthält ungültiges JSON",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple Asset Catalog Format Reference § Contents.json File",
    self_tests=[
        SelfTestCase(
            name="gesund: gültiges Asset Contents.json",
            files={"App/Assets.xcassets/AppIcon.appiconset/Contents.json": _HEALTHY_CONTENTS},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: abgeschnittenes Asset-JSON",
            files={"App/Assets.xcassets/AppIcon.appiconset/Contents.json": '{"images":[\n'},
            expect=Status.FAIL,
        ),
    ],
)
def check_asset_contents_json(ctx: Context) -> CheckResult:
    title = "Asset-Catalog Contents.json enthält ungültiges JSON"
    candidates: list[tuple[str, str]] = []
    for path, rel in _walk_files(ctx):
        parts = rel.replace(os.sep, "/").split("/")
        if (os.path.basename(path) == "Contents.json"
                and any(part.endswith(".xcassets") for part in parts[:-1])):
            candidates.append((path, rel))
    if not candidates:
        return unmeasured("apple.release.asset_contents_json", title,
                          "Kein Contents.json in einem .xcassets-Katalog gefunden.",
                          PLATFORM)
    findings: list[Finding] = []
    for path, rel in candidates:
        try:
            with open(path, "rb") as handle:
                json.load(handle)
        except json.JSONDecodeError as exc:
            findings.append(Finding(
                check_id="apple.release.asset_contents_json",
                severity=Severity.ERROR,
                message=f"Asset Contents.json ist kein gültiges JSON: {exc.msg}.",
                file=rel,
                line=exc.lineno,
                fix="JSON-Syntax korrigieren oder den Asset-Katalog in Xcode neu speichern.",
            ))
        except (OSError, UnicodeError) as exc:
            findings.append(Finding(
                check_id="apple.release.asset_contents_json",
                severity=Severity.ERROR,
                message=f"Asset Contents.json ist nicht lesbar ({type(exc).__name__}).",
                file=rel,
                fix="Kodierung, Dateirechte und Checkout prüfen.",
            ))
    return result_for("apple.release.asset_contents_json", title, findings,
                      len(candidates), "Asset-Contents-Dateien", PLATFORM)


# --------------------------------------------------------------------------
# App-Store-Pflichtangaben im App-Target
#
# Alle vier Checks darunter stammen aus einem einzigen belegten Durchlauf:
# Eine reale macOS-App wurde am 2026-09-22 nach App Store Connect
# hochgeladen. Vier Dinge fehlten, die kein bestehendes Gate gemessen hat —
# jedes davon fällt erst bei Apple auf, nicht beim lokalen Build.
# --------------------------------------------------------------------------

_PROJECT_WITH_APP_TARGET = """// !$*UTF8*$!
{{
objects = {{
        AAA111 /* SampleMac */ = {{
                isa = PBXNativeTarget;
                buildConfigurationList = LLL111 /* Build configuration list */;
                name = SampleMac;
                productType = "com.apple.product-type.application";
        }};
        LLL111 /* Build configuration list */ = {{
                isa = XCConfigurationList;
                buildConfigurations = (
                        CCC111 /* Release */,
                );
        }};
        CCC111 /* Release */ = {{
                isa = XCBuildConfiguration;
                buildSettings = {{
{settings}
                }};
                name = Release;
        }};
}};
}}
"""


def _project_fixture(**settings: str) -> str:
    body = "\n".join(f"\t\t\t\t\t{key} = {value};"
                     for key, value in settings.items())
    return _PROJECT_WITH_APP_TARGET.format(settings=body)


_HEALTHY_SIGNING = _project_fixture(
    DEVELOPMENT_TEAM="ABCDE12345",
    PRODUCT_BUNDLE_IDENTIFIER="com.example.App",
)
_BROKEN_SIGNING = _project_fixture(
    DEVELOPMENT_TEAM='""',
    PRODUCT_BUNDLE_IDENTIFIER="com.example.App",
)

_HEALTHY_IDENTITY_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleDisplayName</key><string>SampleMac</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
</dict></plist>
"""
_BROKEN_IDENTITY_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$(PRODUCT_NAME)</string>
</dict></plist>
"""
_IDENTITY_PROJECT = _project_fixture(
    INFOPLIST_FILE="App/Info.plist",
    PRODUCT_BUNDLE_IDENTIFIER="com.example.App",
)

_SANDBOX_ON = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.app-sandbox</key><true/>
  <key>com.apple.security.network.client</key><true/>
</dict></plist>
"""
_SANDBOX_MISSING = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.network.client</key><true/>
</dict></plist>
"""
_SANDBOX_PROJECT = _project_fixture(
    CODE_SIGN_ENTITLEMENTS="App/App.entitlements",
    SDKROOT="macosx",
    PRODUCT_BUNDLE_IDENTIFIER="com.example.App",
)
# iOS-Gegenprobe: dieselbe fehlende Angabe darf hier NICHT rot werden, sonst
# ist aus der macOS-Regel ein falsch-positiver Befund für jede iOS-App
# geworden.
_IOS_SANDBOX_PROJECT = _project_fixture(
    CODE_SIGN_ENTITLEMENTS="App/App.entitlements",
    SDKROOT="iphoneos",
    IPHONEOS_DEPLOYMENT_TARGET="17.0",
    PRODUCT_BUNDLE_IDENTIFIER="com.example.App",
)

_COMPLETE_CATALOG = json.dumps({
    "sourceLanguage": "de",
    "version": "1.0",
    "strings": {
        "Verbinden": {"localizations": {
            "de": {"stringUnit": {"state": "translated", "value": "Verbinden"}},
            "en": {"stringUnit": {"state": "translated", "value": "Connect"}},
        }},
    },
}, ensure_ascii=False)
_INCOMPLETE_CATALOG = json.dumps({
    "sourceLanguage": "de",
    "version": "1.0",
    "strings": {
        "Verbinden": {"localizations": {
            "de": {"stringUnit": {"state": "translated", "value": "Verbinden"}},
            "en": {"stringUnit": {"state": "translated", "value": "Connect"}},
        }},
        "Trennen": {"localizations": {
            "de": {"stringUnit": {"state": "translated", "value": "Trennen"}},
        }},
    },
}, ensure_ascii=False)
_CATALOG_PROJECT = _project_fixture(
    PRODUCT_BUNDLE_IDENTIFIER="com.example.App",
)


def _plist_for_configuration(ctx: Context, project: str, config: dict) -> tuple[str, str] | None:
    """Info.plist einer Konfiguration über INFOPLIST_FILE auflösen."""
    raw = _setting(config["block"], "INFOPLIST_FILE")
    if not raw or "$(" in raw:
        return None
    base = os.path.dirname(project)
    path = os.path.normpath(os.path.join(base, raw))
    if not os.path.isfile(path):
        return None
    return path, os.path.relpath(path, ctx.root)


def _read_plist(path: str) -> dict | None:
    try:
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


@register(
    "apple.release.app_category_missing",
    "App-Target ohne LSApplicationCategoryType",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple: LSApplicationCategoryType (Information Property List)",
    # Hart ohne Profil: App Store Connect lehnt den Upload ohne Kategorie ab.
    # Ein falsch-positiver Fall ist ausgeschlossen, weil beide zulässigen
    # Bauformen (Plist-Key und INFOPLIST_KEY_*) geprüft werden und ein nicht
    # auflösbares Target UNMEASURED statt FAIL liefert.
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="gesund: Kategorie in der Info.plist",
            files={"P.xcodeproj/project.pbxproj": _IDENTITY_PROJECT,
                   "App/Info.plist": _HEALTHY_IDENTITY_PLIST},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: Kategorie als INFOPLIST_KEY im Target",
            files={"P.xcodeproj/project.pbxproj": _project_fixture(
                INFOPLIST_KEY_LSApplicationCategoryType="public.app-category.utilities",
                PRODUCT_BUNDLE_IDENTIFIER="com.example.App")},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: weder Plist-Key noch Build-Setting",
            files={"P.xcodeproj/project.pbxproj": _IDENTITY_PROJECT,
                   "App/Info.plist": _BROKEN_IDENTITY_PLIST},
            expect=Status.FAIL,
            expect_finding_contains="LSApplicationCategoryType",
        ),
        SelfTestCase(
            # Xcode erzeugt die Info.plist erst beim Build. Die Quelle kann
            # die Angabe nicht enthalten, also ist sie nicht gemessen — ein
            # PASS wäre hier eine falsch grüne Zusage.
            name="nicht gemessen: Info.plist wird generiert",
            files={"P.xcodeproj/project.pbxproj": _project_fixture(
                GENERATE_INFOPLIST_FILE="YES",
                INFOPLIST_FILE="App/Info.plist",
                PRODUCT_BUNDLE_IDENTIFIER="com.example.App")},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_app_category(ctx: Context) -> CheckResult:
    """App Store Connect lehnt einen Upload ohne App-Kategorie ab.

    Gemessen wird die Eigenschaft 'die Kategorie erreicht das gebaute Bundle',
    nicht eine bestimmte Bauform: Xcode erlaubt sie als Schlüssel in der
    Info.plist ODER als INFOPLIST_KEY_* im Target. Beide Wege sind gültig,
    ein Gate, das nur einen verlangt, verbietet den anderen.

    Belegt am 2026-09-22 (reale macOS-App): Im Target unter Identity war 'App Category'
    leer und der Schlüssel fehlte im Custom macOS Application Target
    Properties. Der lokale Build war grün, Apple meldete den Fehler erst
    nach dem Upload.
    """
    check_id = "apple.release.app_category_missing"
    title = "App-Target ohne LSApplicationCategoryType"
    projects = _app_target_projects(ctx)
    if not projects:
        return unmeasured(check_id, title, "Kein .xcodeproj gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unresolved = 0
    for project, rel, configs in projects:
        if not configs:
            continue
        for config in configs:
            if not config["resolved"]:
                unresolved += 1
                continue
            examined += 1
            setting = _setting(config["block"],
                               "INFOPLIST_KEY_LSApplicationCategoryType")
            if setting:
                continue
            plist_entry = _plist_for_configuration(ctx, project, config)
            if plist_entry is None:
                # Kein lesbarer Anzeigeort: bei GENERATE_INFOPLIST_FILE = YES
                # erzeugt Xcode die Datei erst beim Build, die Quelle enthält
                # sie nicht. Das ist NICHT GEMESSEN, nie bestanden — sonst
                # meldet der Check für genau die Projekte grün, deren Angabe
                # er gar nicht sehen kann (belegt an einer veröffentlichten iOS-App, 2026-09-22).
                unresolved += 1
                examined -= 1
                continue
            data = _read_plist(plist_entry[0])
            if data is None:
                unresolved += 1
                examined -= 1
                continue
            if str(data.get("LSApplicationCategoryType") or "").strip():
                continue
            findings.append(Finding(
                check_id=check_id, severity=Severity.ERROR,
                message=f"LSApplicationCategoryType fehlt für Target "
                        f"'{config['target']}' ({config['config']}).",
                file=plist_entry[1] if plist_entry else rel,
                fix="In Xcode unter Target > General > Identity eine App "
                    "Category wählen, oder LSApplicationCategoryType "
                    "(z. B. public.app-category.utilities) in die Info.plist "
                    "schreiben. App Store Connect lehnt den Upload sonst ab.",
                guideline="Apple: LSApplicationCategoryType",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Keine auflösbare App-Target-Konfiguration gefunden "
            f"({unresolved} nicht auflösbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "App-Target-Konfigurationen", PLATFORM)


@register(
    "apple.release.display_name_missing",
    "App-Target ohne CFBundleDisplayName",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="Apple: CFBundleDisplayName (Information Property List)",
    self_tests=[
        SelfTestCase(
            name="gesund: Anzeigename in der Info.plist",
            files={"P.xcodeproj/project.pbxproj": _IDENTITY_PROJECT,
                   "App/Info.plist": _HEALTHY_IDENTITY_PLIST},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: nur CFBundleName, kein Anzeigename",
            files={"P.xcodeproj/project.pbxproj": _IDENTITY_PROJECT,
                   "App/Info.plist": _BROKEN_IDENTITY_PLIST},
            expect=Status.FAIL,
            expect_finding_contains="CFBundleDisplayName",
        ),
    ],
)
def check_display_name(ctx: Context) -> CheckResult:
    """Ohne CFBundleDisplayName zeigt der Finder den Dateinamen.

    Belegt am 2026-09-22 (reale macOS-App): Display Name war im Target unter Identity
    leer. Das bricht keinen Build — es fällt erst auf, wenn die App unter
    ihrem Produktnamen statt ihrem Markennamen im Dock steht.
    """
    check_id = "apple.release.display_name_missing"
    title = "App-Target ohne CFBundleDisplayName"
    projects = _app_target_projects(ctx)
    if not projects:
        return unmeasured(check_id, title, "Kein .xcodeproj gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unresolved = 0
    for project, rel, configs in projects:
        for config in configs:
            if not config["resolved"]:
                unresolved += 1
                continue
            setting = _setting(config["block"],
                               "INFOPLIST_KEY_CFBundleDisplayName")
            if setting:
                examined += 1
                continue
            plist_entry = _plist_for_configuration(ctx, project, config)
            if plist_entry is None:
                unresolved += 1
                continue
            data = _read_plist(plist_entry[0])
            if data is None:
                unresolved += 1
                continue
            examined += 1
            value = str(data.get("CFBundleDisplayName") or "").strip()
            if value:
                continue
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message=f"CFBundleDisplayName fehlt für Target "
                        f"'{config['target']}' ({config['config']}).",
                file=plist_entry[1],
                fix="CFBundleDisplayName in die Info.plist schreiben oder in "
                    "Xcode unter Target > General > Identity > Display Name "
                    "setzen. Ohne den Schlüssel zeigt macOS CFBundleName.",
                guideline="Apple: CFBundleDisplayName",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Keine App-Target-Konfiguration mit auflösbarer Info.plist "
            f"({unresolved} nicht auflösbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "App-Target-Konfigurationen", PLATFORM)


@register(
    "apple.release.signing_team_missing",
    "App-Target ohne DEVELOPMENT_TEAM",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="Apple: Distributing your app for beta testing and releases",
    self_tests=[
        SelfTestCase(
            name="gesund: Team im App-Target gesetzt",
            files={"P.xcodeproj/project.pbxproj": _HEALTHY_SIGNING},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: Team leer im App-Target",
            files={"P.xcodeproj/project.pbxproj": _BROKEN_SIGNING},
            expect=Status.FAIL,
            expect_finding_contains="DEVELOPMENT_TEAM",
        ),
    ],
)
def check_signing_team(ctx: Context) -> CheckResult:
    """DEVELOPMENT_TEAM muss im App-Target stehen, nicht irgendwo in der Datei.

    Der Prüfbereich ist die einzelne Target-Konfiguration. Das bestehende
    `apple.project_settings` sucht denselben Schlüssel mit einem dateiweiten
    re.search — bei einer realen macOS-App blieb es dadurch grün, obwohl das App-Target kein
    Team trug und die Signierung bei Apple scheiterte (2026-09-22).
    """
    check_id = "apple.release.signing_team_missing"
    title = "App-Target ohne DEVELOPMENT_TEAM"
    projects = _app_target_projects(ctx)
    if not projects:
        return unmeasured(check_id, title, "Kein .xcodeproj gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unresolved = 0
    for _project, rel, configs in projects:
        for config in configs:
            if not config["resolved"]:
                unresolved += 1
                continue
            examined += 1
            team = _setting(config["block"], "DEVELOPMENT_TEAM")
            if team:
                continue
            reason = ("ist leer" if team == "" else "fehlt")
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message=f"DEVELOPMENT_TEAM {reason} in Target "
                        f"'{config['target']}' ({config['config']}).",
                file=rel,
                fix="In Xcode unter Target > Signing & Capabilities das Team "
                    "wählen. Ohne Team schlägt die Distributionssignierung "
                    "fehl; ein lokaler Debug-Build bleibt davon unberührt.",
                guideline="Apple: Distributing your app",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Keine auflösbare App-Target-Konfiguration gefunden "
            f"({unresolved} nicht auflösbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "App-Target-Konfigurationen", PLATFORM)


@register(
    "apple.release.app_sandbox_missing",
    "macOS-App ohne App-Sandbox-Entitlement",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple: com.apple.security.app-sandbox (App Sandbox Entitlement)",
    # Hart ohne Profil: App Review verlangt die Sandbox für jede
    # Mac-App-Store-App. Der Check läuft nur auf macOS-Projekten mit
    # auflösbarer Entitlements-Datei, sonst UNMEASURED.
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="gesund: Sandbox aktiviert",
            files={"P.xcodeproj/project.pbxproj": _SANDBOX_PROJECT,
                   "App/App.entitlements": _SANDBOX_ON},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: Entitlements ohne app-sandbox",
            files={"P.xcodeproj/project.pbxproj": _SANDBOX_PROJECT,
                   "App/App.entitlements": _SANDBOX_MISSING},
            expect=Status.FAIL,
            expect_finding_contains="app-sandbox",
        ),
        SelfTestCase(
            name="gesund: iOS-Target ohne Sandbox-Schlüssel",
            files={"P.xcodeproj/project.pbxproj": _IOS_SANDBOX_PROJECT,
                   "App/App.entitlements": _SANDBOX_MISSING},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_app_sandbox(ctx: Context) -> CheckResult:
    """App Review verlangt com.apple.security.app-sandbox für jede Mac-App.

    Gemessen wird der Wert im Entitlement, nicht die Existenz der Datei: eine
    Entitlements-Datei mit Sandbox-Unterschlüsseln, aber ohne den
    Sandbox-Schalter selbst, sieht vollständig aus und ist es nicht.

    Belegt am 2026-09-22 (reale macOS-App): Die Datei trug
    com.apple.security.network.client und files.user-selected.read-write,
    aber nicht com.apple.security.app-sandbox. Unter Signing & Capabilities
    fehlte die Capability 'App Sandbox' deshalb ganz.
    """
    check_id = "apple.release.app_sandbox_missing"
    title = "macOS-App ohne App-Sandbox-Entitlement"
    projects = _app_target_projects(ctx)
    if not projects:
        return unmeasured(check_id, title, "Kein .xcodeproj gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unresolved = 0
    seen: set[str] = set()
    for project, rel, configs in projects:
        for config in configs:
            if not config["resolved"]:
                unresolved += 1
                continue
            # Die Regel gilt für macOS. Ein iOS-Target sandboxt implizit und
            # trägt den Schlüssel nicht — dort wäre der Befund falsch positiv.
            if not config.get("macos"):
                continue
            raw = _setting(config["block"], "CODE_SIGN_ENTITLEMENTS")
            if not raw or "$(" in raw:
                unresolved += 1
                continue
            path = os.path.normpath(os.path.join(os.path.dirname(project), raw))
            if not os.path.isfile(path):
                findings.append(Finding(
                    check_id=check_id, severity=Severity.ERROR,
                    message=f"CODE_SIGN_ENTITLEMENTS zeigt auf '{raw}', "
                            f"die Datei fehlt.",
                    file=rel,
                    fix="Pfad korrigieren oder die Entitlements-Datei anlegen.",
                ))
                examined += 1
                continue
            entitlements_rel = os.path.relpath(path, ctx.root)
            if entitlements_rel in seen:
                continue
            seen.add(entitlements_rel)
            data = _read_plist(path)
            if data is None:
                unresolved += 1
                continue
            examined += 1
            if data.get("com.apple.security.app-sandbox") is True:
                continue
            present = "com.apple.security.app-sandbox" in data
            message = ("com.apple.security.app-sandbox steht auf "
                       f"{data.get('com.apple.security.app-sandbox')!r}."
                       if present else
                       "com.apple.security.app-sandbox fehlt im Entitlement.")
            findings.append(Finding(
                check_id=check_id, severity=Severity.ERROR,
                message=message,
                file=entitlements_rel,
                fix="In Xcode unter Signing & Capabilities die Capability "
                    "'App Sandbox' hinzufügen, oder "
                    "com.apple.security.app-sandbox = true in die "
                    "Entitlements schreiben. App Review verlangt sie für "
                    "jede Mac-App-Store-App.",
                guideline="Apple: App Sandbox Entitlement",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Keine macOS-App-Konfiguration mit auflösbarer "
            f"Entitlements-Datei ({unresolved} nicht auflösbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "Entitlements-Dateien", PLATFORM)


@register(
    "apple.release.xcstrings_incomplete",
    "String Catalog hat unübersetzte Schlüssel",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="Apple: Localizing and varying text with a string catalog",
    self_tests=[
        SelfTestCase(
            name="gesund: alle Sprachen vollständig",
            files={"P.xcodeproj/project.pbxproj": _CATALOG_PROJECT,
                   "App/Localizable.xcstrings": _COMPLETE_CATALOG},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: ein Schlüssel ohne englische Übersetzung",
            files={"P.xcodeproj/project.pbxproj": _CATALOG_PROJECT,
                   "App/Localizable.xcstrings": _INCOMPLETE_CATALOG},
            expect=Status.FAIL,
            expect_finding_contains="en",
        ),
    ],
)
def check_xcstrings_complete(ctx: Context) -> CheckResult:
    """Ein halb gepflegter Katalog sieht aus wie eine Quelle und ist keine.

    Der Prüfgegenstand ist der Kandidat: gezählt werden alle Schlüssel des
    Katalogs, nicht nur die Lücken. Die erwarteten Sprachen werden aus dem
    Katalog selbst abgeleitet (jede Sprache, die irgendein Schlüssel trägt) —
    eine gepflegte Sprachliste im Gate wäre die zweite Liste.

    Belegt am 2026-09-22 (reale macOS-App): Der Katalog wuchs von 27 auf 52 Schlüssel,
    47 davon blieben in mindestens einer Sprache unübersetzt. In der App war
    die Oberfläche dadurch nur teilweise lokalisiert.
    """
    check_id = "apple.release.xcstrings_incomplete"
    title = "String Catalog hat unübersetzte Schlüssel"
    candidates = [(path, rel) for path, rel in _walk_files(ctx)
                  if rel.endswith(".xcstrings")]
    if not candidates:
        return unmeasured(check_id, title,
                          "Kein .xcstrings-Katalog gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unreadable = 0
    for path, rel in candidates:
        try:
            with open(path, "rb") as handle:
                data = json.load(handle)
        except Exception:
            # Syntaxfehler meldet apple.release.xcstrings_json; hier wäre er
            # ein zweiter Befund für dieselbe Ursache.
            unreadable += 1
            continue
        if not isinstance(data, dict):
            unreadable += 1
            continue
        strings = data.get("strings")
        if not isinstance(strings, dict) or not strings:
            continue

        expected: set[str] = set()
        source = str(data.get("sourceLanguage") or "").strip()
        if source:
            expected.add(source)
        for entry in strings.values():
            if isinstance(entry, dict):
                localizations = entry.get("localizations")
                if isinstance(localizations, dict):
                    expected |= set(localizations.keys())
        if len(expected) < 2:
            # Einsprachiger Katalog: es gibt keine Lücke zu messen.
            continue

        incomplete: list[tuple[str, list[str]]] = []
        for key, entry in strings.items():
            if not isinstance(entry, dict):
                continue
            examined += 1
            # Ein Schlüssel, der ausdrücklich nicht übersetzt werden soll,
            # ist kein Befund — das ist Apples eigener Schalter dafür.
            if entry.get("shouldTranslate") is False:
                continue
            localizations = entry.get("localizations")
            localizations = localizations if isinstance(localizations, dict) else {}
            missing: list[str] = []
            for language in sorted(expected):
                unit = localizations.get(language)
                if not isinstance(unit, dict):
                    # Der Quellsprache darf der Eintrag fehlen: dann ist der
                    # Schlüssel selbst der Text.
                    if language != source:
                        missing.append(language)
                    continue
                state = str(
                    (unit.get("stringUnit") or {}).get("state") or ""
                ).strip()
                if state in {"needs_review", "new", "stale"}:
                    missing.append(language)
            if missing:
                incomplete.append((key, missing))

        if incomplete:
            languages = sorted({lang for _key, langs in incomplete
                                for lang in langs})
            preview = ", ".join(repr(key[:40]) for key, _ in incomplete[:3])
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message=f"{len(incomplete)} von {len(strings)} Schlüsseln "
                        f"unvollständig ({', '.join(languages)}): {preview}"
                        f"{' …' if len(incomplete) > 3 else ''}.",
                file=rel,
                fix="Katalog in Xcode öffnen und die offenen Sprachen füllen, "
                    "oder shouldTranslate=false setzen, wo Absicht. Eine "
                    "halb gefüllte Sprache wirkt im UI wie ein Bug.",
                guideline="Apple: String Catalogs",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Kein mehrsprachiger Katalog mit Schlüsseln gefunden "
            f"({unreadable} nicht lesbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "Katalogschlüssel", PLATFORM)
