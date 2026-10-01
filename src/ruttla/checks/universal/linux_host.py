"""Offline host snapshots: the reproduced tzdata Host-area failure."""

from __future__ import annotations

import json
import posixpath

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, unmeasured,
)

_ID = "linux.tzdata_host_timezone"
_TITLE = "tzdata: localtime verweist auf eine nicht registrierte Host-Zeitzone"
_GUIDE = "GUIDELINES.md § Linux host preflight"
_MARKER = "ruttla_host_snapshot"


def _snapshot(target="/usr/share/zoneinfo/Etc/UTC", **overrides):
    data = {
        _MARKER: 1, "os_id": "ubuntu", "localtime_target": target,
        "tzdata_config_present": True, "tzdata_zone_templates": ["Etc", "Europe"],
    }
    data.update(overrides)
    return {"ops/host.json": json.dumps(data)}


@register(
    _ID, _TITLE, severity=Severity.WARNING, guideline=_GUIDE,
    references=(
        "https://manpages.debian.org/testing/debconf-doc/debconf-devel.7.en.html",
        "https://sources.debian.org/src/tzdata/2026c-1/debian/tzdata.config/",
    ),
    rationale=(
        "Reproduced on a fresh Linux container: /etc/timezone was Etc/UTC, but "
        "/etc/localtime linked to /usr/share/zoneinfo/Host. tzdata derived area "
        "Host and FSET tzdata/Zones/Host returned 10 because that template did "
        "not exist. Only explicit version-1 snapshots with target template "
        "metadata are measured offline; this is not a remote server audit. "
        "Custom registered Host templates are accepted. Other timezone aliases "
        "are not classified as invalid by this bounded check."
    ),
    self_tests=[
        SelfTestCase("gesund: UTC", _snapshot(), Status.PASS),
        SelfTestCase("gesund: Europe", _snapshot("/usr/share/zoneinfo/Europe/Berlin"), Status.PASS),
        SelfTestCase("gesund: eigene Host-Vorlage", _snapshot(
            "/usr/share/zoneinfo/Host", tzdata_zone_templates=["Etc", "Host"]), Status.PASS),
        SelfTestCase("defekt: Host", _snapshot("/usr/share/zoneinfo/Host"),
                     Status.FAIL, expect_finding_contains="tzdata/Zones/Host"),
        SelfTestCase("defekt: Host-Unterpfad", _snapshot("/usr/share/zoneinfo/Host/Localtime"), Status.FAIL),
        SelfTestCase("defekt: timezone-Datei kaschiert Host nicht", _snapshot(
            "/usr/share/zoneinfo/Host", timezone_file="Etc/UTC"), Status.FAIL),
        SelfTestCase("keine Vorlagen", _snapshot(tzdata_zone_templates=[]), Status.UNMEASURED),
        SelfTestCase("unbekanntes Schema", _snapshot(ruttla_host_snapshot=2), Status.UNMEASURED),
        SelfTestCase("bool ist keine Schemaversion", _snapshot(ruttla_host_snapshot=True), Status.UNMEASURED),
        SelfTestCase("ungültiger Feldtyp", _snapshot(localtime_target=[]), Status.UNMEASURED),
        SelfTestCase("kein tzdata", _snapshot(tzdata_config_present=False), Status.UNMEASURED),
        SelfTestCase("reguläre localtime-Datei", _snapshot(localtime_target=None), Status.UNMEASURED),
        SelfTestCase("anderes System", _snapshot(os_id="alpine"), Status.UNMEASURED),
        SelfTestCase("ungültiges JSON", {"ops/host.json": '{"ruttla_host_snapshot":1,'}, Status.UNMEASURED),
        SelfTestCase("fremdes JSON", {"data.json": '{"localtime_target":"/usr/share/zoneinfo/Host"}'}, Status.UNMEASURED),
        SelfTestCase("teilweise Eingabe", {
            **_snapshot(), "ops/incomplete.json": '{"ruttla_host_snapshot":1}'}, Status.UNMEASURED),
        SelfTestCase("Defekt neben ungültigem Snapshot bleibt rot", {
            **_snapshot("/usr/share/zoneinfo/Host"),
            "ops/incomplete.json": '{"ruttla_host_snapshot":1}'}, Status.FAIL),
    ],
)
def check_tzdata_host_timezone(ctx: Context) -> CheckResult:
    """Measure only the reproduced unsupported Host area in supplied snapshots."""
    findings = []
    incomplete = []
    units = 0
    for source in ctx.files(".json"):
        if _MARKER not in source.text:
            continue
        try:
            data = json.loads(source.text)
        except (ValueError, RecursionError):
            incomplete.append(source.rel)
            continue
        if not isinstance(data, dict) or _MARKER not in data:
            continue
        target = data.get("localtime_target")
        templates = data.get("tzdata_zone_templates")
        if (
            type(data[_MARKER]) is not int or data[_MARKER] != 1
            or data.get("os_id") not in ("ubuntu", "debian")
            or data.get("tzdata_config_present") is not True
            or not isinstance(target, str) or not target.startswith("/usr/share/zoneinfo/")
            or not isinstance(templates, list) or not templates
            or not all(isinstance(t, str) and t for t in templates)
        ):
            incomplete.append(source.rel)
            continue
        normalized = posixpath.normpath(target)
        if not normalized.startswith("/usr/share/zoneinfo/"):
            incomplete.append(source.rel)
            continue
        units += 1
        area = normalized.removeprefix("/usr/share/zoneinfo/").split("/", 1)[0]
        if area != "Host" or "Host" in templates:
            continue
        findings.append(Finding(
            check_id=_ID, severity=Severity.WARNING, file=source.rel,
            message="localtime verwendet Host, aber tzdata/Zones/Host ist nicht registriert; FSET scheitert mit Exit 10.",
            evidence="localtime: Host; keine passende tzdata-Vorlage im Snapshot.",
            fix="Link sichern, auf eine gewünschte installierte Zone (z. B. Etc/UTC) setzen; dpkg --configure -a und dpkg --audit prüfen. Bei Mount-/Rechtefehlern Provider kontaktieren.",
            guideline=_GUIDE,
        ))
    if incomplete and not findings:
        result = unmeasured(_ID, _TITLE, "Unvollständige/ungültige Host-Snapshots: " + ", ".join(incomplete))
        result.units_examined = units
        result.unit_label = "Host-Snapshots"
        return result
    result = result_for(_ID, _TITLE, findings, units, "Host-Snapshots")
    if incomplete:
        result.reason = "Zusätzlich ungemessene Snapshots: " + ", ".join(incomplete)
    return result
