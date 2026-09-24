"""Canonical run report. Every reporter renders THIS dict and nothing else.

Schema policy (ADR-0007): ``schema_version`` is major.minor; fields are only
added within a major version. JSON Schema: ``schemas/report.schema.json``.
"""

from __future__ import annotations

from .. import __version__
from ..context import Context
from ..engine import EXIT_CRASH, EXIT_FAILED, EXIT_OK, EXIT_UNMEASURED
from ..models import SCHEMA_VERSION, CheckResult
from ..platforms import PLATFORMS_WITHOUT_PACK

# Kept for report schema 1.x compatibility (ADR-0001); `tool_name` is the
# public name. `tool` switches to "ruttla" with schema 2.0.
LEGACY_TOOL_ID = "master_quality_gate"
TOOL_NAME = "ruttla"

VERDICTS = {
    EXIT_OK: "green",
    EXIT_FAILED: "failed",
    EXIT_UNMEASURED: "unmeasured",
    EXIT_CRASH: "crash",
}


def _next_action(verdict: str, advisory: int, skipped: int) -> str:
    # Die nächste Handlung explizit benennen — die CLI soll nicht raten.
    if verdict == "green":
        action = ("Keine blockierenden Befunde. Nicht gemessene Checks im "
                  "Abschnitt 'unmeasured' prüfen, bevor 'geprüft' gemeldet wird.")
        if advisory:
            action += f" {advisory} nicht blockierende Befunde (blocking=false) ansehen."
    elif verdict == "failed":
        action = ("Die Befunde mit blocking=true beheben. Jeder Befund trägt "
                  "file, line und fix.")
    elif verdict == "unmeasured":
        action = ("NICHTS wurde gemessen — das ist kein Erfolg. Grund je Check "
                  "im Feld 'reason'.")
    else:
        action = "Mindestens ein Check ist abgestürzt. Siehe 'reason'."
    if skipped:
        action += (f" {skipped} Datei(en) wegen gate.max_file_bytes NICHT geprüft "
                   "— siehe coverage.files_skipped.")
    return action


def build_report(ctx: Context, results: list[CheckResult], exit_code: int,
                 max_findings: int) -> dict:
    counts = {
        "pass": sum(1 for r in results if r.status.value == "pass"),
        "fail": sum(1 for r in results if r.status.value == "fail"),
        "unmeasured": sum(1 for r in results if r.status.value == "unmeasured"),
        "error": sum(1 for r in results if r.status.value == "error"),
    }
    sev = {"error": 0, "warning": 0, "info": 0}
    blocking_total = advisory_total = 0
    for r in results:
        for f in r.findings:
            sev[f.severity.value] += 1
            if f.blocking:
                blocking_total += 1
            else:
                advisory_total += 1

    verdict = VERDICTS[exit_code]
    coverage = ctx.coverage().to_dict()
    detected = ctx.platforms()

    out_results = []
    emitted_sev = {"error": 0, "warning": 0, "info": 0}
    truncated_total = 0
    for r in results:
        d = r.to_dict()
        total = len(d["findings"])
        emitted = min(total, max_findings)
        truncated = total - emitted
        d["findings_total"] = total
        d["findings_emitted"] = emitted
        d["findings_truncated"] = truncated
        d["blocking_findings"] = sum(1 for f in r.findings if f.blocking)
        d["findings"] = d["findings"][:max_findings]
        truncated_total += truncated
        for finding in d["findings"]:
            emitted_sev[finding["severity"]] += 1
        out_results.append(d)

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": LEGACY_TOOL_ID,
        "tool_name": TOOL_NAME,
        "tool_version": __version__,
        "root": ctx.root,
        "verdict": verdict,
        "exit_code": exit_code,
        "next_action": _next_action(verdict, advisory_total,
                                    coverage["files_skipped_total"]),
        "platforms_detected": sorted(detected),
        "platforms_without_pack": sorted(p for p in detected if p in PLATFORMS_WITHOUT_PACK),
        "profile": ctx.config.profile_path,
        "strict": ctx.config.strict,
        "checks": counts,
        "blocking_findings": blocking_total,
        "advisory_findings": advisory_total,
        "findings_by_severity": sev,
        "findings_emitted_by_severity": emitted_sev,
        "findings_truncated": truncated_total,
        "files_scanned": coverage["files_scanned"],
        "coverage": coverage,
        "results": out_results,
    }


def runner_state_report(kind: str, message: str, exit_code: int) -> dict:
    """Machine-readable result when no scan report can be built."""
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": LEGACY_TOOL_ID,
        "tool_name": TOOL_NAME,
        "tool_version": __version__,
        "verdict": "unmeasured" if exit_code == EXIT_UNMEASURED else "crash",
        "exit_code": exit_code,
        "runner_state": {"id": kind, "message": message},
    }
