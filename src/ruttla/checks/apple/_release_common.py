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

Shared helpers and fixtures of this pack (not a rule module).
"""

from __future__ import annotations

import fnmatch
import json
import os
import plistlib
import re
import urllib.parse
import xml.etree.ElementTree as ET

from ruttla.core import Context, DEFAULT_EXCLUDE_DIRS, SkippedFile


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
                size = os.path.getsize(path)
            except OSError:
                continue
            if size > ctx.config.max_file_bytes:
                # Visible like every other size skip (P02-T008), never silent.
                posix = rel.replace(os.sep, "/")
                skipped = ctx.coverage().skipped
                if not any(item.rel == posix for item in skipped):
                    skipped.append(SkippedFile(posix, "max_file_bytes", size))
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
    objects_match = re.search(r"^[ \t]*objects\s*=\s*\{", text, re.MULTILINE)
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
    objects_match = re.search(r"^[ \t]*objects\s*=\s*\{", text, re.MULTILINE)
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
    match = re.search(rf"^[ \t]*{re.escape(key)}\s*=\s*(.*?);\s*$",
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
