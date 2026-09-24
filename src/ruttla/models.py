"""Domain model: result states, severities, findings and self-test probes.

Central design decisions (unchanged from the original gate):

* Every check has THREE outcomes: PASS / FAIL / UNMEASURED. "Not measured" is
  a state of its own, never silently green. A check that could not build its
  input reports UNMEASURED with a reason.
* Every finding carries a stable ID (``brand.hardcoded_name``), file, line,
  evidence and a fix hint. The ID is the contract for every consumer — no
  display text ever becomes an anchor.
* Checks measure PROPERTIES, not code shapes.
* Every check ships its own sabotage probes (``self_tests``) so that "a gate
  that was never red" cannot exist.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

# Report schema version (ADR-0007): major.minor, additive fields bump minor.
# 1.1 (2026-09-24): blocking/advisory model, coverage diagnostics,
#                   tool_name/tool_version, platforms_without_pack.
SCHEMA_VERSION = "1.1"


class GateInputError(RuntimeError):
    """Die Eingabe konnte nicht zuverlässig gelesen oder bestimmt werden."""


class ConfigError(GateInputError):
    """Das Gate-Profil ist vorhanden, aber ungültig oder nicht lesbar."""


class ChangedFilesError(GateInputError):
    """Die geänderten Dateien konnten nicht sicher bestimmt werden."""


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNMEASURED = "unmeasured"
    ERROR = "error"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    """Ein einzelner Befund. `check_id` + `file` + `line` identifizieren ihn."""

    check_id: str
    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None
    evidence: str | None = None
    fix: str | None = None
    guideline: str | None = None
    # Set by the engine's exit policy: does this finding decide the exit
    # code (True) or is it advisory (False)? None = not evaluated yet.
    blocking: bool | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["blocking"] = bool(self.blocking)
        return d


@dataclass
class CheckResult:
    check_id: str
    status: Status
    title: str
    findings: list[Finding] = field(default_factory=list)
    # Warum nicht gemessen wurde — Pflicht bei UNMEASURED, sonst ist der
    # dritte Ausgang wertlos.
    reason: str | None = None
    # Was der Check tatsächlich angefasst hat. Null Einheiten bei einem
    # inhaltlichen Check ist verdächtig und wird vom Runner geprüft.
    units_examined: int = 0
    unit_label: str = "Dateien"
    platform: str = "universal"

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "status": self.status.value,
            "platform": self.platform,
            "reason": self.reason,
            "units_examined": self.units_examined,
            "unit_label": self.unit_label,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class SelfTestCase:
    """Eine Sabotage-Probe: Dateien anlegen, Check laufen lassen, Ausgang erwarten."""

    name: str
    files: dict[str, str]
    expect: Status
    # Wenn gesetzt: dieser Befund muss unter den Findings sein.
    expect_finding_contains: str | None = None
