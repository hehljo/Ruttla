"""SARIF 2.1.0 reporter (ADR-0008) for GitHub Code Scanning and other CI.

Mapping:
    check_id            → ruleId (stable)
    rule title          → rule.shortDescription
    rationale           → rule.fullDescription / rule.help
    severity            → level  (error / warning / note)
    file + line         → physicalLocation (uri relative to %SRCROOT%)
    message + fix       → result.message
    finding identity    → partialFingerprints["ruttla/v1"]
    unmeasured / crash  → invocation.toolExecutionNotifications

GitHub rejects the WHOLE upload if any result lacks a location
("locationFromSarifResult: expected at least one location"). Project-level
findings (no file) are therefore anchored on a deterministic project file and
flagged with ``properties.projectLevel = true``.
"""

from __future__ import annotations

import hashlib

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

_LEVEL = {"error": "error", "warning": "warning", "info": "note"}
_PROBLEM_SEVERITY = {"error": "error", "warning": "warning", "info": "recommendation"}


def fingerprint(finding: dict) -> str:
    """Stable identity of a finding that survives line moves (P06 prepares
    baselines on top of this): rule, file and the normalised evidence."""
    evidence = " ".join(str(finding.get("evidence") or finding.get("message") or "").split())
    file_norm = (finding.get("file") or "").replace("\\", "/")
    raw = "\x1f".join((finding["check_id"], file_norm, evidence))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _first_paragraph(text: str) -> str:
    return text.strip().split("\n\n", 1)[0].replace("\n", " ").strip()


def _rule_descriptor(check_id: str, meta: dict | None) -> dict:
    if meta is None:  # a result from a rule unknown to the catalog
        return {"id": check_id, "name": check_id,
                "shortDescription": {"text": check_id}}
    rationale = meta.get("rationale") or ""
    help_lines = [meta["title"], ""]
    if rationale:
        help_lines += [rationale, ""]
    if meta.get("guideline"):
        help_lines.append(f"Guideline: {meta['guideline']}")
    for ref in meta.get("references", []):
        help_lines.append(f"Reference: {ref}")
    help_lines.append(f"Explain locally: ruttla --explain {check_id}")
    severity = meta["default_severity"]
    return {
        "id": check_id,
        "name": "".join(part.capitalize() for part in check_id.replace(".", "_").split("_")),
        "shortDescription": {"text": meta["title"]},
        "fullDescription": {"text": _first_paragraph(rationale) or meta["title"]},
        "help": {"text": "\n".join(help_lines).strip()},
        "defaultConfiguration": {"level": _LEVEL[severity]},
        "properties": {
            "tags": meta.get("tags", []),
            "precision": "high" if meta.get("safe_by_default") else "medium",
            "problem.severity": _PROBLEM_SEVERITY[severity],
            "pack": meta["pack"],
            "lifecycle": meta.get("lifecycle", "stable"),
            "introducedIn": meta.get("introduced_in"),
        },
    }


def _project_anchor(report: dict, scanned: list[str]) -> str:
    profile = report.get("profile")
    candidates = []
    if profile:
        candidates.append(profile.replace("\\", "/").rsplit("/", 1)[-1])
    candidates.append("README.md")
    for name in candidates:
        if name in scanned:
            return name
    if profile:
        return candidates[0]
    return scanned[0] if scanned else "README.md"


def build_sarif(report: dict, rules: dict[str, dict], scanned_files: list[str]) -> dict:
    """Render the canonical report as SARIF. ``rules`` maps check_id → metadata."""
    anchor = _project_anchor(report, sorted(scanned_files))
    rule_ids = [r["check_id"] for r in report["results"]]
    descriptors = [_rule_descriptor(cid, rules.get(cid)) for cid in rule_ids]
    index = {cid: i for i, cid in enumerate(rule_ids)}

    results = []
    notifications = []
    for res in report["results"]:
        if res["status"] in ("unmeasured", "error"):
            notifications.append({
                "level": "warning" if res["status"] == "unmeasured" else "error",
                "message": {"text": f"{res['status']}: {res['reason']}"},
                "descriptor": {"id": res["check_id"]},
            })
        for f in res["findings"]:
            text = f["message"]
            if f.get("fix"):
                text += f" Fix: {f['fix']}"
            project_level = not f.get("file")
            uri = (f.get("file") or anchor).replace("\\", "/")
            location = {"artifactLocation": {"uri": uri,
                                             "uriBaseId": "%SRCROOT%"}}
            if f.get("line") and not project_level:
                location["region"] = {"startLine": int(f["line"])}
            result = {
                "ruleId": f["check_id"],
                "ruleIndex": index[res["check_id"]],
                "level": _LEVEL[f["severity"]],
                "message": {"text": text},
                "locations": [{"physicalLocation": location}],
                "partialFingerprints": {"ruttla/v1": fingerprint(f)},
                "properties": {"blocking": bool(f.get("blocking")),
                               "projectLevel": project_level},
            }
            results.append(result)
    for skipped in report.get("coverage", {}).get("files_skipped", []):
        skipped_file = skipped["file"].replace("\\", "/")
        notifications.append({
            "level": "warning",
            "message": {"text": f"not scanned ({skipped['reason']}, "
                                f"{skipped['bytes']} bytes): {skipped_file}"},
        })

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [{
            "tool": {"driver": {
                "name": "Ruttla",
                "version": report.get("tool_version", "0"),
                "semanticVersion": report.get("tool_version", "0"),
                "rules": descriptors,
            }},
            "invocations": [{
                "executionSuccessful": report["exit_code"] != 3,
                "exitCode": report["exit_code"],
                "toolExecutionNotifications": notifications,
            }],
            "results": results,
            "columnKind": "unicodeCodePoints",
            "properties": {
                "verdict": report["verdict"],
                "reportSchemaVersion": report["schema_version"],
                "blockingFindings": report.get("blocking_findings", 0),
                "advisoryFindings": report.get("advisory_findings", 0),
                "checks": report["checks"],
            },
        }],
    }
