"""Apple release: shared schemes and archive configuration.

Split from the original checks/apple_release.py; background and
shared helpers in _release_common.py.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from ruttla.core import (
    CheckResult,
    Context,
    failed,
    Finding,
    ok,
    register,
    result_for,
    SelfTestCase,
    Severity,
    Status,
    to_posix,
    unmeasured,
)

from ._release_common import (
    _configuration_names,
    _elements,
    _HEALTHY_PROJECT,
    _HEALTHY_SCHEME,
    _local_tag,
    _project_dirs,
    _read_project,
    _referenced_project,
    _shared_schemes,
    _target_ids,
    _xml_root,
    PLATFORM,
)


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
        file=to_posix(os.path.relpath(projects[0], ctx.root)),
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
