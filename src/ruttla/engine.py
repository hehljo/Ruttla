"""Rule loading, execution, result validation and the exit-code policy.

Exit codes are a public contract (docs/CONTRACTS.md):

    0  measured, no blocking finding (advisory findings may exist)
    1  at least one blocking finding
    2  nothing meaningful was measured — NOT a success
    3  runner, input, config or plugin error
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import sys
import traceback

from .config import Config
from .context import Context
from .models import CheckResult, Severity, Status
from .registry import REGISTRY, Check

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNMEASURED = 2
EXIT_CRASH = 3

OFFICIAL_PACKAGE = "ruttla.checks"


class PluginLoadError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def official_rule_modules() -> list[str]:
    """Dotted names of all official rule modules, deterministic order.

    Modules whose last name starts with '_' are shared helpers, not rules.
    Rules are loaded ONLY from the installed package — never from the scan
    target (ADR-0005).
    """
    package = importlib.import_module(OFFICIAL_PACKAGE)
    names = []
    for info in pkgutil.walk_packages(package.__path__, OFFICIAL_PACKAGE + "."):
        leaf = info.name.rsplit(".", 1)[-1]
        if info.ispkg or leaf.startswith("_"):
            continue
        names.append(info.name)
    return sorted(names)


def _load_official() -> None:
    modules = official_rule_modules()
    if not modules:
        raise PluginLoadError("Null Check-Module gefunden — der Runner prüft nichts.")
    for name in modules:
        before = set(REGISTRY)
        already = name in sys.modules
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            for check_id in set(REGISTRY) - before:
                REGISTRY.pop(check_id, None)
            sys.modules.pop(name, None)
            raise PluginLoadError(
                f"Plugin fehlgeschlagen: {name}: {type(exc).__name__}: {exc}"
            ) from exc
        if already:
            # Imported earlier in this process: its checks must still be in
            # the registry (a test may have swapped the registry out).
            owned = [c for c in REGISTRY.values() if c.fn.__module__ == name]
            if not owned:
                sys.modules.pop(name, None)
                module = importlib.import_module(name)
                owned = [c for c in REGISTRY.values() if c.fn.__module__ == name]
            if not owned:
                raise PluginLoadError(f"Plugin registriert keinen Check: {name}")
            continue
        if not set(REGISTRY) - before:
            sys.modules.pop(name, None)
            raise PluginLoadError(f"Plugin registriert keinen Check: {name}")
        del module


def _load_directory(checks_dir: str) -> None:
    """Load every ``*.py`` in a trusted directory (tests / development only).

    Never pass a directory that belongs to the scan target (ADR-0005).
    """
    if not os.path.isdir(checks_dir):
        raise PluginLoadError(f"Check-Verzeichnis fehlt: {checks_dir}")
    candidates = [
        name for name in sorted(os.listdir(checks_dir))
        if name.endswith(".py") and not name.startswith("_")
    ]
    if not candidates:
        raise PluginLoadError("Null Check-Module gefunden — der Runner prüft nichts.")

    registered = 0
    for name in candidates:
        path = os.path.join(checks_dir, name)
        module_name = f"qg_checks_{name[:-3]}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Plugin nicht ladbar: {name}")
        before = set(REGISTRY)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            for check_id in set(REGISTRY) - before:
                REGISTRY.pop(check_id, None)
            sys.modules.pop(module_name, None)
            raise PluginLoadError(
                f"Plugin fehlgeschlagen: {name}: {type(exc).__name__}: {exc}"
            ) from exc
        added = set(REGISTRY) - before
        if not added:
            sys.modules.pop(module_name, None)
            raise PluginLoadError(f"Plugin registriert keinen Check: {name}")
        registered += len(added)
    if registered == 0:
        raise PluginLoadError("Null Checks registriert — der Runner prüft nichts.")


def load_checks(checks_dir: str | None = None) -> None:
    """Lädt jedes Check-Modul und belegt, dass es mindestens einen Check
    registriert. Ein syntaktisch ladbares, aber leeres Plugin ist kein Lauf."""
    if checks_dir is not None:
        _load_directory(checks_dir)
    else:
        _load_official()
    if not REGISTRY:
        raise PluginLoadError("Null Checks registriert — der Runner prüft nichts.")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _crashed_check(check: Check, reason: str) -> CheckResult:
    return CheckResult(
        check.id, Status.ERROR, check.title, reason=reason, platform=check.platform,
    )


def validate_result(check: Check, result: object) -> CheckResult:
    if not isinstance(result, CheckResult):
        return _crashed_check(
            check, f"Ungültiges Plugin-Ergebnis: {type(result).__name__} statt CheckResult."
        )
    if result.check_id != check.id:
        return _crashed_check(
            check, f"Plugin-Ergebnis trägt falsche Check-ID: {result.check_id!r}."
        )
    if not isinstance(result.status, Status):
        return _crashed_check(check, f"Ungültiger Check-Status: {result.status!r}.")
    if result.status == Status.UNMEASURED and not result.reason:
        return _crashed_check(check, "UNMEASURED ohne reason ist kein gültiges Ergebnis.")
    if result.status == Status.ERROR and not result.reason:
        return _crashed_check(check, "ERROR ohne reason ist kein gültiges Ergebnis.")
    if result.status in (Status.PASS, Status.FAIL) and result.units_examined <= 0:
        return _crashed_check(
            check, "PASS/FAIL mit null geprüften Einheiten ist kein gültiges Ergebnis."
        )
    if result.status == Status.FAIL and not result.findings:
        return _crashed_check(check, "FAIL ohne Befund ist kein gültiges Ergebnis.")
    return result


# Legacy private name used by older callers.
_validate_result = validate_result


def selector_matches(pattern: str, check_id: str) -> bool:
    return check_id == pattern or (
        pattern.endswith("*") and check_id.startswith(pattern[:-1])
    )


def run_checks(ctx: Context, *, only_platform: str | None,
               only_checks: list[str], changed: list[str] | None) -> list[CheckResult]:
    results: list[CheckResult] = []
    platforms = ctx.platforms()
    for check in REGISTRY.values():
        if only_platform and check.platform != only_platform:
            continue
        if only_checks and not any(selector_matches(c, check.id) for c in only_checks):
            continue
        if not only_platform and not only_checks and check.platform not in platforms:
            continue
        try:
            severity = ctx.config.severity_for(check.id, check.default_severity)
            if severity is None:
                continue  # im Profil abgeschaltet
            res = validate_result(check, check.fn(ctx))
        except Exception:
            res = _crashed_check(
                check, "Check abgestürzt:\n" + traceback.format_exc(limit=4)
            )
        # Die Schwere aus dem Profil überschreibt die der Befunde.
        for f in res.findings:
            if f.severity != Severity.INFO or severity == Severity.ERROR:
                f.severity = severity
            f.guideline = f.guideline or check.guideline
        if changed is not None:
            keep = [f for f in res.findings if f.file is None or f.file in changed]
            if res.findings and not keep:
                res.status = Status.PASS
            res.findings = keep
        results.append(res)
    return results


# ---------------------------------------------------------------------------
# Exit policy
# ---------------------------------------------------------------------------

def worst_exit(results: list[CheckResult]) -> int:
    """Severity-only view (legacy API): ignores profile and safe_by_default."""
    if any(r.status == Status.ERROR for r in results):
        return EXIT_CRASH
    has_error_finding = any(
        f.severity == Severity.ERROR
        for r in results if r.status == Status.FAIL
        for f in r.findings
    )
    if has_error_finding:
        return EXIT_FAILED
    measured = [r for r in results if r.status in (Status.PASS, Status.FAIL)]
    if not measured:
        return EXIT_UNMEASURED
    return EXIT_OK


def is_blocking(result: CheckResult, severity: Severity, config: Config,
                safe_ids: set[str]) -> bool:
    """The single definition of "this finding decides the exit code".

    * ``--strict`` / ``gate.strict``: every finding of a failed check blocks.
    * with a profile: every finding at severity ``error`` blocks.
    * without a profile: only ``error`` findings of ``safe_by_default``
      checks block — an unknown project must not go red over things that
      work.
    """
    if result.status != Status.FAIL:
        return False
    if config.strict:
        return True
    if severity != Severity.ERROR:
        return False
    return bool(config.profile_path) or result.check_id in safe_ids


def apply_exit_policy(results: list[CheckResult], config: Config) -> int:
    """Mark every finding blocking/advisory and derive the exit code.

    Equivalent to the pre-0.1 runner logic (worst_exit + strict promotion +
    profile-less downgrade), but the decision is now recorded per finding.
    """
    safe_ids = {c.id for c in REGISTRY.values() if c.safe_by_default}
    any_blocking = False
    for res in results:
        for f in res.findings:
            f.blocking = is_blocking(res, f.severity, config, safe_ids)
            any_blocking = any_blocking or f.blocking
    if any(r.status == Status.ERROR for r in results):
        return EXIT_CRASH
    if any_blocking:
        return EXIT_FAILED
    if not any(r.status in (Status.PASS, Status.FAIL) for r in results):
        return EXIT_UNMEASURED
    return EXIT_OK
