"""Check registry, public rule metadata (P01-T005) and helpers for checks."""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterator, Sequence

from .discovery import SourceFile, strip_comments
from .models import CheckResult, Finding, SelfTestCase, Severity, Status

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context

# Every rule that existed before the first public version is recorded as
# introduced in 0.1.0 (ADR-0007).
BASELINE_VERSION = "0.1.0"
LIFECYCLES = ("experimental", "stable", "deprecated")
_URL = re.compile(r"https?://[^\s\"'<>)]+")


@dataclass
class Check:
    id: str
    title: str
    platform: str
    default_severity: Severity
    fn: Callable[["Context"], CheckResult]
    guideline: str = ""
    self_tests: list[SelfTestCase] = field(default_factory=list)
    # True = dieser Check ist auch ohne Profil hart. Nur für Prüfungen, die in
    # einem fremden Projekt nicht falsch-positiv werden können.
    safe_by_default: bool = False
    # --- public rule metadata (all optional, additive) --------------------
    tags: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    rationale: str = ""
    introduced_in: str = BASELINE_VERSION
    lifecycle: str = "stable"
    deprecated_in: str | None = None
    replaced_by: str | None = None

    @property
    def pack(self) -> str:
        return self.platform

    @property
    def namespace(self) -> str:
        return self.id.split(".", 1)[0]

    def rationale_text(self) -> str:
        """Explicit rationale, else the check function's docstring."""
        if self.rationale:
            return inspect.cleandoc(self.rationale)
        return inspect.cleandoc(self.fn.__doc__ or "")

    def all_references(self) -> list[str]:
        refs = list(self.references)
        for url in _URL.findall(self.rationale_text()) + _URL.findall(self.guideline):
            url = url.rstrip(".,;:")
            if url not in refs:
                refs.append(url)
        return refs

    def all_tags(self) -> list[str]:
        tags = [f"pack:{self.pack}", self.namespace]
        if self.safe_by_default:
            tags.append("blocking-by-default")
        tags.extend(t for t in self.tags if t not in tags)
        return tags

    def metadata(self) -> dict:
        """Public, JSON-serialisable rule record (docs, --list, SARIF, --explain)."""
        return {
            "id": self.id,
            "title": self.title,
            "pack": self.pack,
            "default_severity": self.default_severity.value,
            "safe_by_default": self.safe_by_default,
            "lifecycle": self.lifecycle,
            "introduced_in": self.introduced_in,
            "deprecated_in": self.deprecated_in,
            "replaced_by": self.replaced_by,
            "tags": self.all_tags(),
            "guideline": self.guideline,
            "references": self.all_references(),
            "rationale": self.rationale_text(),
            "self_tests": [
                {"name": case.name, "expect": case.expect.value}
                for case in self.self_tests
            ],
        }


REGISTRY: dict[str, Check] = {}


def register(
    check_id: str,
    title: str,
    platform: str = "universal",
    severity: Severity = Severity.WARNING,
    guideline: str = "",
    self_tests: Sequence[SelfTestCase] = (),
    safe_by_default: bool = False,
    *,
    tags: Sequence[str] = (),
    references: Sequence[str] = (),
    rationale: str = "",
    introduced_in: str = BASELINE_VERSION,
    lifecycle: str = "stable",
    deprecated_in: str | None = None,
    replaced_by: str | None = None,
):
    if lifecycle not in LIFECYCLES:
        raise ValueError(f"Unbekannter Lifecycle für {check_id}: {lifecycle}")

    def deco(fn: Callable[["Context"], CheckResult]):
        if check_id in REGISTRY:
            raise RuntimeError(f"Doppelte Check-ID: {check_id}")
        REGISTRY[check_id] = Check(
            id=check_id, title=title, platform=platform,
            default_severity=severity, fn=fn, guideline=guideline,
            self_tests=list(self_tests), safe_by_default=safe_by_default,
            tags=tuple(tags), references=tuple(references), rationale=rationale,
            introduced_in=introduced_in, lifecycle=lifecycle,
            deprecated_in=deprecated_in, replaced_by=replaced_by,
        )
        return fn
    return deco


# ---------------------------------------------------------------------------
# Hilfsfunktionen für Checks
# ---------------------------------------------------------------------------

def ok(check_id: str, title: str, units: int, label: str = "Dateien",
       platform: str = "universal") -> CheckResult:
    """Bestanden — aber null geprüfte Einheiten sind NICHT bestanden.

    "0 von 0 Dateien sauber" ist trivial wahr und sagt nichts. Jede Suche nach
    einem Muster braucht davor die Prüfung, dass überhaupt etwas zu
    durchsuchen war; sonst ist die stärkste Aussage des Gates die, die am
    leichtesten falsch grün wird.
    """
    if units <= 0:
        return CheckResult(
            check_id, Status.UNMEASURED, title,
            reason=f"Null {label} geprüft — es gab nichts zu messen.",
            units_examined=0, unit_label=label, platform=platform,
        )
    return CheckResult(check_id, Status.PASS, title, units_examined=units,
                       unit_label=label, platform=platform)


def unmeasured(check_id: str, title: str, reason: str,
               platform: str = "universal") -> CheckResult:
    return CheckResult(check_id, Status.UNMEASURED, title, reason=reason,
                       platform=platform)


def failed(check_id: str, title: str, findings: list[Finding], units: int,
           label: str = "Dateien", platform: str = "universal") -> CheckResult:
    return CheckResult(check_id, Status.FAIL, title, findings=findings,
                       units_examined=units, unit_label=label, platform=platform)


def result_for(check_id: str, title: str, findings: list[Finding], units: int,
               label: str = "Dateien", platform: str = "universal") -> CheckResult:
    if findings:
        return failed(check_id, title, findings, units, label, platform)
    return ok(check_id, title, units, label, platform)


def iter_matches(sf: SourceFile, pattern: re.Pattern, *,
                 skip_comments: bool = True) -> Iterator[tuple[int, re.Match, str]]:
    """Liefert (Zeilennummer, Match, Zeilentext) — Kommentare optional entfernt."""
    haystack = strip_comments(sf.text, sf.ext) if skip_comments else sf.text
    for m in pattern.finditer(haystack):
        line_no = haystack.count("\n", 0, m.start()) + 1
        raw_lines = sf.lines
        raw = raw_lines[line_no - 1] if 0 < line_no <= len(raw_lines) else ""
        yield line_no, m, raw.strip()


def snippet(text: str, limit: int = 120) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 1] + "…"
