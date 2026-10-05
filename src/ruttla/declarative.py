"""Declarative rules (``ruttla-rule/0``) executed by the Rust engine (ADR-0011).

A rule is data under ``ruttla/rules/<platform>/<id>.toml``. Python reads only
the catalogue metadata and the fixtures; matching happens exclusively in
``ruttla-engine`` (linear-time ``regex`` crate). A missing engine makes these
rules *not measured* — never silently green — and ``--engine required`` turns
that into a runner error.

Never two live implementations of one rule: a declarative rule whose ID is
still registered as a Python check is SHADOWED (not run). It exists only
while a port is in progress; ``tests/test_engine_declarative.py`` keeps the shadow
list empty, and ``scripts/engine_diff.py findings`` compares both sides.
"""

from __future__ import annotations

import json
import os
import subprocess
import sysconfig
import tempfile
import tomllib
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from .models import CheckResult, Finding, GateInputError, SelfTestCase, Severity, Status
from .registry import BASELINE_VERSION, REGISTRY, Check

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context

RULE_FORMAT = "ruttla-rule/0"
ENGINE_MODES = ("auto", "off", "required")
ENGINE_TIMEOUT_S = 900
# Exit 3 der Engine: Fehlbedienung oder ungültige Regeln/Manifest.
ENGINE_USAGE_EXIT = 3

# Declarative rule IDs that still have a Python check (port in progress).
SHADOWED: dict[str, Check] = {}
# Zusätzliche Regelverzeichnisse (installierte Hub-Pakete, ``hub.register_locked``).
# Sie laufen im selben Engine-Lauf wie die offiziellen Regeln.
EXTRA_RULE_DIRS: list[Path] = []
_mode = os.environ.get("RUTTLA_ENGINE", "auto")


class EngineError(RuntimeError):
    """Engine required but missing, or the engine rejected its input."""


def set_engine_mode(mode: str) -> None:
    global _mode
    if mode not in ENGINE_MODES:
        raise ValueError(f"--engine {mode}: erlaubt sind {', '.join(ENGINE_MODES)}")
    _mode = mode


def engine_mode() -> str:
    return _mode


def rules_dir() -> Path:
    return Path(str(resources.files(__package__).joinpath("rules")))


def find_engine() -> Path | None:
    """RUTTLA_ENGINE_BIN · Skriptordner dieses Interpreters · Build im eigenen Checkout.

    Bewusst KEINE Suche über PATH oder das aktuelle Verzeichnis: Ruttla läuft
    in fremden Repos, und unter Windows sucht ``shutil.which`` zuerst im
    aktuellen Verzeichnis — ein ``ruttla-engine.exe`` im Prüfziel würde sonst
    ausgeführt (ADR-0005: Zielcode wird nie ausgeführt).
    """
    if _mode == "off":
        return None
    override = os.environ.get("RUTTLA_ENGINE_BIN")
    if override:
        return Path(override) if Path(override).is_file() else None
    names = ("ruttla-engine.exe", "ruttla-engine") if os.name == "nt" else ("ruttla-engine",)
    scripts = sysconfig.get_path("scripts")
    if scripts:
        for name in names:
            installed = Path(scripts) / name
            if installed.is_file():
                return installed
    repo = Path(__file__).resolve().parents[2]
    if not (repo / "engine" / "Cargo.toml").is_file():
        return None
    built = [repo / "engine" / "target" / profile / name
             for profile in ("release", "debug") for name in names]
    built = [b for b in built if b.is_file()]
    # Das jüngste Build: ein veraltetes Release-Binary misst sonst den alten Stand.
    return max(built, key=lambda b: b.stat().st_mtime) if built else None


def _missing_reason() -> str:
    if _mode == "off":
        return "Engine abgeschaltet (--engine off) — deklarative Regel nicht gemessen."
    return ("ruttla-engine nicht gefunden — deklarative Regel nicht gemessen "
            "(cargo build in engine/ oder RUTTLA_ENGINE_BIN setzen).")


def _cases(rule: dict) -> list[SelfTestCase]:
    return [SelfTestCase(name=f["name"], files=dict(f["files"]), expect=Status(f["expect"]),
                         expect_finding_contains=f.get("expect_finding_contains"),
                         expect_findings=f.get("expect_findings"))
            for f in rule.get("fixtures", [])]


def make_check(rule: dict) -> Check:
    check_id = rule["id"]

    def run(ctx: "Context") -> CheckResult:
        view = "scoped" if ctx.scope is not None else "unscoped"
        return run_engine_rules(ctx.unscoped(), [check_id], view=view)[check_id]

    run.__name__ = run.__qualname__ = "declarative_" + check_id.replace(".", "_")
    return Check(
        id=check_id, title=rule["title"], platform=rule["platform"],
        default_severity=Severity(rule["severity"]), fn=run,
        guideline=rule.get("guideline", ""), self_tests=_cases(rule),
        safe_by_default=bool(rule.get("safe_by_default", False)),
        tags=tuple(rule.get("tags", ())), references=tuple(rule.get("references", ())),
        rationale=rule.get("rationale", ""),
        introduced_in=rule.get("introduced_in", BASELINE_VERSION),
        lifecycle=rule.get("lifecycle", "stable"), engine=True,
    )


def read_rules(directory: Path | None = None) -> list[dict]:
    """All rule files, sorted by path. Structural validation is the engine's
    job (``ruttla-engine check-rules``); here only what Python itself needs."""
    directory = directory or rules_dir()
    if not directory.is_dir():
        return []
    rules = []
    for path in sorted(directory.rglob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise EngineError(f"Regeldatei nicht lesbar: {path.name}: {exc}") from exc
        if data.get("format") != RULE_FORMAT or path.stem != data.get("id"):
            raise EngineError(f"{path.name}: kein {RULE_FORMAT} oder Dateiname ≠ id")
        rules.append(data)
    return rules


def load_declarative() -> int:
    """Register every declarative rule; returns the number registered."""
    added = 0
    for rule in read_rules():
        check = make_check(rule)
        existing = REGISTRY.get(check.id)
        if existing is not None and not existing.engine:
            SHADOWED[check.id] = check
            continue
        if existing is None:
            REGISTRY[check.id] = check
            added += 1
    return added


def _engine_args(ctx: "Context") -> list[str]:
    cfg = ctx.config
    args = ["--max-file-bytes", str(cfg.max_file_bytes)]
    for d in cfg.exclude_dirs:
        args += ["--exclude-dir", d]
    for g in cfg.exclude_globs:
        args += ["--exclude-glob", g]
    return args


def _to_result(data: dict) -> CheckResult:
    return CheckResult(
        check_id=data["check_id"], status=Status(data["status"]), title=data["title"],
        findings=[Finding(check_id=f["check_id"], severity=Severity(f["severity"]),
                          message=f["message"], file=f["file"], line=f["line"],
                          evidence=f["evidence"], fix=f["fix"], guideline=f["guideline"])
                  for f in data["findings"]],
        reason=data["reason"], units_examined=data["units_examined"],
        unit_label=data["unit_label"], platform=data["platform"],
    )


def run_engine_rules(ctx: "Context", check_ids: list[str], *, view: str = "scoped",
                     rules: Path | None = None) -> dict[str, CheckResult]:
    """One engine pass for all ``check_ids`` on ``ctx.root``."""
    if not check_ids:
        return {}
    binary = find_engine()
    if binary is None:
        if _mode == "required":
            raise EngineError("ruttla-engine fehlt, aber --engine required gesetzt.")
        out = {}
        for cid in check_ids:
            check = REGISTRY.get(cid) or SHADOWED[cid]
            out[cid] = CheckResult(cid, Status.UNMEASURED, check.title, reason=_missing_reason(),
                                   platform=check.platform)
        return out
    dirs = [rules] if rules is not None else [rules_dir(), *EXTRA_RULE_DIRS]
    cmd = [str(binary), "scan", ctx.root, "--view", view, *_engine_args(ctx)]
    for d in dirs:
        cmd += ["--rules", str(d)]
    for cid in check_ids:
        cmd += ["--rule", cid]
    # Ausgabe in eine Datei, nie in eine Pipe: ein hängender Kindprozess hält
    # sonst den Lauf offen, auch nach dem Timeout.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as out, \
            tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err:
        try:
            proc = subprocess.run(cmd, stdout=out, stderr=err, timeout=ENGINE_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise EngineError(f"ruttla-engine nach {ENGINE_TIMEOUT_S}s abgebrochen") from exc
        out.seek(0)
        err.seek(0)
        raw, stderr = out.read(), err.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    if proc.returncode == 2 and "error" in data:
        raise GateInputError(data["error"]["message"])
    if proc.returncode != 0 or "results" not in data:
        detail = data.get("error", {}).get("message") or stderr.strip() or raw.strip()
        raise EngineError(f"ruttla-engine Exit {proc.returncode}: {detail[:2000]}")
    return {r["check_id"]: _to_result(r) for r in data["results"]}
