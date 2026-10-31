"""`ruttla guard --base REF`: hat ein Fix die Prüfung umgangen statt den Fehler behoben?

Für Agenten-Fixes, vor dem Commit: verglichen wird der Arbeitsbaum (inklusive
ungetrackter Dateien) mit REF. Rot wird der Wächter, wenn der Diff

* die Prüf-Policy anfasst (Profil, `.ruttla/`, Workflows, CODEOWNERS, `.gitignore`),
* mehr Unterdrückungs-Kommentare enthält als vorher (`noqa`, `eslint-disable` …),
* weniger Testdefinitionen enthält als vorher (Code samt Test gelöscht).

Gezählt wird je geänderter Datei vor und nach dem Diff; geprüft sind damit
genau die Dateien, die der Fix berührt. Exit: 0 sauber · 1 Umgehung · 3 Fehler.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# Pfade, deren Änderung die Prüfung selbst verändert. Ein Präfix mit "/" am Ende
# deckt den ganzen Ordner.
POLICY_PATHS = (".ruttla.toml", ".qualitygate.toml", ".ruttla/", ".github/workflows/",
                ".github/CODEOWNERS", "CODEOWNERS", ".gitignore")

# Linearzeitige Muster (kein verschachteltes Quantifizieren): je Treffer eine
# Unterdrückung einer Prüfung, sprachübergreifend.
SUPPRESSION = re.compile(
    r"#\s*noqa\b|#\s*type:\s*ignore\b|#\s*pragma:\s*no\s*cover\b|#\s*pylint:\s*disable"
    r"|eslint-disable|@ts-ignore|@ts-expect-error|@ts-nocheck|biome-ignore|prettier-ignore"
    r"|swiftlint:disable|//\s*nolint\b|#\[allow\(|@SuppressWarnings|#pragma\s+warning\s+disable"
    r"|@warning_ignore|gdlint:\s*ignore|rubocop:disable|ruttla[-:]ignore|NOSONAR"
    # Übersprungene Tests zählen mit: ein Skip macht einen roten Test still grün.
    r"|@pytest\.mark\.(?:skip|xfail)|@unittest\.(?:skip|expectedFailure)|pytest\.skip\("
    r"|\.skipTest\(|\b(?:it|test|describe)\.(?:skip|todo)\(|\bx(?:it|describe|test)\("
    r"|@Disabled\b|@Ignore\b|\[Ignore\]|#\[ignore\]|XCTSkip|\bt\.Skip\(")

# Testdefinitionen, sprachübergreifend; nur in Dateien, die nach Test aussehen.
TEST_DEF = re.compile(
    r"^[ \t]*(?:async[ \t]+)?def[ \t]+test\w*[ \t]*\("
    r"|^[ \t]*(?:it|test|describe)(?:\.\w+)?[ \t]*\("
    r"|^[ \t]*(?:override[ \t]+)?func[ \t]+test\w*[ \t]*\("
    r"|@Test\b|\[(?:Test|Fact|Theory|TestMethod)\]|#\[test\]"
    r"|^[ \t]*func[ \t]+test_\w*[ \t]*\(", re.M)
_TEST_PATH = re.compile(r"(?:^|/)(?:tests?|spec|__tests__)/|(?:^|/)test_[^/]*$"
                        r"|_test\.\w+$|\.(?:test|spec)\.\w+$|Tests?\.\w+$|(?:^|/)\w*Tests/")


class GuardError(RuntimeError):
    pass


def _git(root: str, *args: str) -> bytes:
    try:
        done = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GuardError(f"Git-Aufruf fehlgeschlagen: {exc}") from exc
    if done.returncode != 0:
        raise GuardError(os.fsdecode(done.stderr).strip() or f"git {' '.join(args)}")
    return done.stdout


def toplevel(root: str) -> str:
    return os.fsdecode(_git(root, "rev-parse", "--show-toplevel")).strip()


def changed(top: str, base: str) -> list[str]:
    """Geänderte, gelöschte und ungetrackte Pfade des ganzen Repos (relativ zu ``top``).

    Immer das ganze Repo, auch wenn ein Unterordner geprüft wird: eine Policy-Datei
    an der Wurzel wirkt auf jeden Unterordner. ``--no-renames`` liefert bei einer
    Verschiebung alten UND neuen Pfad — sonst verschwände eine Testdatei, die an
    einen Nicht-Test-Pfad verschoben wird, aus der Zählung.
    """
    if not base or base.startswith("-") or "\0" in base:
        raise GuardError("Ungültige Git-Referenz für --base.")
    _git(top, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    names = _git(top, "diff", "--name-only", "--no-renames", "-z", base, "--")
    extra = _git(top, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted({os.fsdecode(n) for n in (names + extra).split(b"\0") if n})


def _old(root: str, base: str, rel: str) -> str:
    try:
        return _git(root, "show", f"{base}:./{rel}").decode("utf-8", "replace")
    except GuardError:
        return ""  # Datei gab es in REF nicht


def _new(root: str, rel: str) -> str:
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return ""
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "replace")


def is_policy(rel: str) -> bool:
    """Groß-/Kleinschreibung egal (macOS/Windows lesen `.RUTTLA.toml` als Profil);
    Profil, `.ruttla/` und `.gitignore` auf jeder Ebene, `.github/` an der Wurzel."""
    low = rel.lower()
    parts = low.split("/")
    if parts[-1] in (".gitignore", ".ruttla.toml", ".qualitygate.toml", "codeowners"):
        return True
    if ".ruttla" in parts[:-1]:
        return True
    return any(low.startswith(p.lower()) if p.endswith("/") else low == p.lower()
               for p in POLICY_PATHS)


def is_test_file(rel: str) -> bool:
    return bool(_TEST_PATH.search(rel))


def inspect(root: str, base: str) -> dict:
    top = toplevel(root)
    files = changed(top, base)
    policy = [f for f in files if is_policy(f)]
    suppressions, tests = [], []
    for rel in files:
        if is_policy(rel):
            continue
        # Kein Überspringen „binärer“ Dateien: ein eingefügtes NUL-Byte würde sonst
        # jede Zählung abschalten. Die Muster laufen auch über ersetzte Bytes.
        old, new = _old(top, base, rel), _new(top, rel)
        before, after = len(SUPPRESSION.findall(old)), len(SUPPRESSION.findall(new))
        if after > before:
            suppressions.append({"file": rel, "before": before, "after": after})
        if is_test_file(rel):
            t_before, t_after = len(TEST_DEF.findall(old)), len(TEST_DEF.findall(new))
            if t_after < t_before:
                tests.append({"file": rel, "before": t_before, "after": t_after})
    return {"base": base, "files_checked": len(files), "policy_changed": policy,
            "suppressions_added": suppressions, "tests_removed": tests}


def verdict(result: dict) -> int:
    return 1 if (result["policy_changed"] or result["suppressions_added"]
                 or result["tests_removed"]) else 0


def render(result: dict) -> str:
    lines = []
    for rel in result["policy_changed"]:
        lines.append(f"POLICY\t{rel}\tPrüf-Policy geändert — gehört in einen eigenen, "
                     "von einem Menschen geprüften Commit")
    for s in result["suppressions_added"]:
        lines.append(f"SUPPRESSION\t{s['file']}\t{s['before']} → {s['after']} Unterdrückungen/"
                     "Skips — Ursache beheben statt Prüfung oder Test abschalten")
    for t in result["tests_removed"]:
        lines.append(f"TESTS\t{t['file']}\t{t['before']} → {t['after']} Testdefinitionen "
                     "— Test entfernt statt Fehler behoben")
    code = verdict(result)
    lines.append(f"GUARD\t{'clean' if code == 0 else 'bypass'}\t{result['files_checked']} "
                 f"geänderte Dateien gegen {result['base']}")
    return "\n".join(lines)


def run_guard_command(argv: list[str], prog: str = "ruttla") -> int:
    ap = argparse.ArgumentParser(
        prog=f"{prog} guard",
        description="Prüft einen Fix auf Umgehung: Policy geändert, Unterdrückungen "
                    "hinzugefügt oder Tests entfernt (Arbeitsbaum gegen --base).",
        epilog="Exit: 0 sauber · 1 Umgehung · 3 Fehler")
    ap.add_argument("root", nargs="?", default=".", help="Projektwurzel (Vorgabe .)")
    ap.add_argument("--base", required=True, help="Referenz vor dem Fix, z. B. origin/main")
    ap.add_argument("--format", choices=("agent", "json"), default="agent")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    try:
        result = inspect(os.path.abspath(args.root), args.base)
    except GuardError as exc:
        print(f"RUNNER_ERROR\tguard_failed\t{exc}", file=sys.stderr)
        return 3
    if args.format == "json":
        import json

        print(json.dumps({**result, "exit_code": verdict(result)}, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    return verdict(result)
