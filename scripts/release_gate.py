#!/usr/bin/env python3
"""Release-Gate: misst die Abnahmekriterien K1–K9 aus MASTER_ROADMAP_V1.md.

Je Kriterium drei Ausgänge: bestanden · durchgefallen · nicht gemessen.
Ein Kriterium besteht aus Teilprüfungen: fällt eine durch, ist es durchgefallen;
fällt keine durch, aber eine ist nicht messbar (Netz fehlt, Artefakt noch nicht
definiert), ist es *nicht gemessen* — nie bestanden. Nur Standardbibliothek.

  release_gate.py [--root PFAD] [--allow-network] [--only K2,K3] [--json]

K4: „Verhalten ohne Engine entschieden“ (E3) ist nicht maschinenlesbar und
nicht Teil der Messung.
Netzabhängiges (K1, K7) läuft nur mit --allow-network (gh, PyPI), sonst
„nicht gemessen“. Ruttla und Skripte aus --root werden als Unterprozess gestartet.

Exit: 0 alle gemessenen Kriterien bestanden und keines offen · 1 mindestens eines
durchgefallen · 2 keines durchgefallen, aber mindestens eines nicht gemessen ·
3 Bedienfehler.

Dateinamen, die spätere Pakete anlegen müssen (Verträge dieses Skripts):
  R2  tests/golden/cli_*, schemas/rule*.schema.json, tests/golden/{baseline,stats,sarif}*
  R7  docs/audits/{TRADEMARK,PROVENANCE,HISTORY}_AUDIT_<JJJJ-MM-TT>.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]

PASS, FAIL, UNMEASURED = "bestanden", "durchgefallen", "nicht gemessen"

TARGET_VERSION = "1.0.0"
CI_RUNS_IN_A_ROW = 3
ENGINE_TARGETS_REQUIRED = 5  # K4: Linux x86_64/arm64, macOS x86_64/arm64, Windows
MAX_AUDIT_AGE_DAYS = 30  # K8: „aktuell“ = Bericht höchstens so alt (Entscheidung R8, nicht gemessen)
# K2: Vorschau-Marker im Anzeigepfad. Gemessen 14.11.2026: README, Classifier, drei Doku-Dateien.
PREVIEW_MARKER = re.compile(r"\b(dev0|preview|beta)\b", re.IGNORECASE)
PREVIEW_SCAN = ("README.md", "README.de.md", "pyproject.toml")  # plus docs/*.md (oberste Ebene)
# K6: interne Planungsdokumente, die nicht in den öffentlichen Baum gehören.
# Kandidatenliste aus R5-1 (Entscheidung E5 steht aus) — hier die einzige Fassung.
INTERNAL_DOCS = (
    "STATUS.md", "LESSONS_LEARNED.md",
    "docs/PROJECT_BRIEF.md", "docs/PRODUCT_VISION.md", "docs/RESEARCH_NOTES.md", "docs/FUTURE.md",
    "docs/MODEL_ORCHESTRATION.md", "docs/PUBLIC_RELEASE.md", "docs/REQUIREMENTS.md",
    "docs/RISK_REGISTER.md", "docs/CURRENT_STATE.md", "docs/TECH_STACK.md",
    "docs/operations/1blu-vps.md",
)
# K3: Vertragsfläche → (Stichwort in docs/CONTRACTS.md, Artefakt, das sie sichert).
# Artefakt: ("glob", [Muster]) · ("tests", Datei, [Regexe]) · ("check_ids",)
CONTRACT_SURFACES = (
    ("CLI-Schalter", r"CLI flags", ("glob", ["tests/golden/cli_*"])),
    ("Exit-Codes", r"Exit codes", ("tests", "tests/test_contracts.py",
        [r"def test_exit_zero", r"def test_exit_one", r"def test_exit_two", r"def test_exit_three"])),
    ("Profil", r"Profile", ("tests", "tests/test_contracts.py",
        [r"def test_config_version", r"def test_new_profile_name_is_read"])),
    ("JSON-Report", r"JSON report", ("glob", ["schemas/report.schema.json"])),
    ("Agent-Format", r"Agent format", ("tests", "tests/test_contracts.py",
        [r"def test_agent_format_only_appends_fields"])),
    ("SARIF", r"SARIF", ("glob", ["tests/golden/sarif*", "schemas/sarif*"])),
    ("Check-IDs", r"Check IDs", ("check_ids",)),
    ("Regelformat", r"Rule format", ("glob", ["schemas/rule*.schema.json", "tests/golden/rule_format*"])),
    ("Selbsttest-Export", r"Self-test export", ("glob", ["schemas/selftests.schema.json"])),
    ("Baseline", r"Baseline", ("glob", ["tests/golden/baseline*", "schemas/baseline*"])),
    ("Stats-Export", r"Stats export", ("glob", ["tests/golden/stats*", "schemas/stats*"])),
)

Part = tuple[str, str]  # (PASS | FAIL | UNMEASURED, Text)


@dataclass
class Ctx:
    root: Path
    allow_network: bool
    today: dt.date
    run: Callable[[list[str], Path], tuple[int | None, str]]
    fetch: Callable[[str], tuple[int | None, str]]


@dataclass
class Result:
    key: str
    title: str
    parts: list[Part] = field(default_factory=list)

    @property
    def status(self) -> str:
        states = {s for s, _ in self.parts}
        if FAIL in states:
            return FAIL
        if UNMEASURED in states or not self.parts:
            return UNMEASURED
        return PASS


def real_run(cmd: list[str], cwd: Path) -> tuple[int | None, str]:
    """Unterprozess mit Zeitlimit; None = nicht gestartet oder Zeit überschritten."""
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return done.returncode, done.stdout + done.stderr


def real_fetch(url: str) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 (feste https-URLs)
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (OSError, ValueError) as exc:
        return None, str(exc)


def read(ctx: Ctx, rel: str) -> str | None:
    try:
        return (ctx.root / rel).read_text(encoding="utf-8")
    except OSError:
        return None


def ruttla(ctx: Ctx, *args: str) -> tuple[int | None, str]:
    return ctx.run([sys.executable, "-m", "ruttla", *args], ctx.root)


def versions(ctx: Ctx) -> tuple[str | None, str | None]:
    init = read(ctx, "src/ruttla/__init__.py") or ""
    cargo = read(ctx, "engine/Cargo.toml") or ""
    py = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.M)
    rs = re.search(r'^version\s*=\s*"([^"]+)"', cargo, re.M)
    return (py.group(1) if py else None), (rs.group(1) if rs else None)


def gh_json(ctx: Ctx, *args: str) -> tuple[bool, object]:
    rc, out = ctx.run(["gh", *args], ctx.root)
    if rc != 0:
        return False, out.strip()[:200]
    try:
        return True, json.loads(out)
    except ValueError:
        return False, "keine JSON-Antwort"


NO_NET: Part = (UNMEASURED, "Netzzugriff nicht erlaubt (--allow-network)")


def k1(ctx: Ctx) -> list[Part]:
    if not ctx.allow_network:
        return [NO_NET]
    ok, runs = gh_json(ctx, "run", "list", "--workflow", "CI", "--branch", "main",
                       "--limit", str(CI_RUNS_IN_A_ROW), "--json", "status,conclusion")
    if not ok or not isinstance(runs, list):
        return [(UNMEASURED, f"gh run list nicht lesbar: {runs}")]
    good = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") == "success"]
    if len(runs) < CI_RUNS_IN_A_ROW:
        return [(FAIL, f"nur {len(runs)} CI-Läufe auf main, verlangt {CI_RUNS_IN_A_ROW}")]
    if len(good) < CI_RUNS_IN_A_ROW:
        return [(FAIL, f"{len(good)} von {CI_RUNS_IN_A_ROW} letzten CI-Läufen auf main grün")]
    return [(PASS, f"{CI_RUNS_IN_A_ROW} letzte CI-Läufe auf main grün")]


def k2(ctx: Ctx) -> list[Part]:
    parts: list[Part] = []
    py, rs = versions(ctx)
    for name, value in (("__version__", py), ("Cargo-Version", rs)):
        if value is None:
            parts.append((FAIL, f"{name} nicht lesbar"))
        elif value != TARGET_VERSION:
            parts.append((FAIL, f"{name} ist {value}, verlangt {TARGET_VERSION}"))
    toml = read(ctx, "pyproject.toml") or ""
    if "Development Status :: 5 - Production/Stable" not in toml:
        parts.append((FAIL, "Classifier „5 - Production/Stable“ fehlt"))
    docs = sorted((ctx.root / "docs").glob("*.md")) if (ctx.root / "docs").is_dir() else []
    files = [ctx.root / n for n in PREVIEW_SCAN] + docs
    hits: list[str] = []
    scanned = 0
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        scanned += 1
        for no, line in enumerate(lines, 1):
            if line.lstrip().startswith(('"Development Status', "'Development Status")):
                continue  # Classifier ist oben eigens geprüft
            if PREVIEW_MARKER.search(line):
                hits.append(f"{path.relative_to(ctx.root).as_posix()}:{no}")
    if scanned == 0:
        parts.append((UNMEASURED, "keine Datei für den Vorschau-Suchlauf gefunden"))
    elif hits:
        parts.append((FAIL, f"{len(hits)} Vorschau-Marker (dev0/preview/beta), z. B. {', '.join(hits[:4])}"))
    if not parts:
        parts.append((PASS, f"Version {TARGET_VERSION} in beiden Quellen, Classifier stabil, "
                            f"{scanned} Dateien ohne Vorschau-Marker"))
    return parts


def registry_ids(ctx: Ctx) -> set[str] | None:
    rc, out = ruttla(ctx, "--list", "--format", "json")
    if rc != 0:
        return None
    try:
        return {r["id"] for r in json.loads(out)["rules"]}
    except (ValueError, KeyError, TypeError):
        return None


def k3(ctx: Ctx) -> list[Part]:
    contracts = read(ctx, "docs/CONTRACTS.md")
    if contracts is None:
        return [(FAIL, "docs/CONTRACTS.md fehlt")]
    missing_doc: list[str] = []
    missing_guard: list[str] = []
    unmeasured: list[str] = []
    for name, keyword, guard in CONTRACT_SURFACES:
        if not re.search(keyword, contracts, re.IGNORECASE):
            missing_doc.append(name)
        kind = guard[0]
        if kind == "glob":
            if not any(any(ctx.root.glob(pat)) for pat in guard[1]):
                missing_guard.append(name)
        elif kind == "tests":
            text = read(ctx, guard[1]) or ""
            if not all(re.search(rx, text) for rx in guard[2]):
                missing_guard.append(name)
        else:  # check_ids: Registry ⊆ Golden
            golden = read(ctx, "tests/golden/check_ids.txt")
            ids = registry_ids(ctx)
            if golden is None:
                missing_guard.append(name)
            elif ids is None:
                unmeasured.append(name)
            else:
                absent = ids - set(golden.split())
                if absent:
                    missing_guard.append(f"{name} ({len(absent)} von {len(ids)} IDs nicht eingefroren)")
    parts: list[Part] = []
    if missing_doc:
        parts.append((FAIL, "in CONTRACTS.md nicht genannt: " + ", ".join(missing_doc)))
    if missing_guard:
        parts.append((FAIL, "ohne Schema/Golden/Test: " + ", ".join(missing_guard)))
    if unmeasured:
        parts.append((UNMEASURED, "Registry nicht lesbar für: " + ", ".join(unmeasured)))
    if not parts:
        parts.append((PASS, f"alle {len(CONTRACT_SURFACES)} Vertragsflächen genannt und gesichert"))
    return parts


def engine_binary(ctx: Ctx) -> Path | None:
    for sub in ("release", "debug"):
        for exe in ("ruttla-engine", "ruttla-engine.exe"):
            cand = ctx.root / "engine" / "target" / sub / exe
            if cand.is_file():
                return cand
    return None


def engine_selftest(ctx: Ctx) -> Part:
    binary = engine_binary(ctx)
    if binary is None:
        return (UNMEASURED, "kein Engine-Binary gebaut (engine/target)")
    rc, out = ctx.run([str(binary), "selftest", "--rules", "src/ruttla/rules"], ctx.root)
    if rc is None:
        return (UNMEASURED, f"ruttla-engine selftest nicht gelaufen: {out[:120]}")
    return (PASS, "ruttla-engine selftest grün") if rc == 0 else (FAIL, f"ruttla-engine selftest Exit {rc}")


def k4(ctx: Ctx) -> list[Part]:
    parts: list[Part] = []
    wf = read(ctx, ".github/workflows/release.yml")
    if wf is None:
        parts.append((FAIL, "release.yml fehlt"))
    else:
        targets = set(re.findall(r"target:\s*([A-Za-z0-9_-]+-[A-Za-z0-9_.-]+)", wf))
        if len(targets) < ENGINE_TARGETS_REQUIRED:
            parts.append((FAIL, f"release.yml baut {len(targets)} Ziele, verlangt {ENGINE_TARGETS_REQUIRED}"))
        if "SHA256SUMS" not in wf:
            parts.append((FAIL, "release.yml erzeugt keine SHA256SUMS"))
    for name in ("install.sh", "install.ps1"):
        text = read(ctx, name)
        if text is None:
            parts.append((FAIL, f"{name} fehlt"))
        elif not re.search(r"sha256|Get-FileHash", text, re.IGNORECASE):
            parts.append((FAIL, f"{name} prüft keine Prüfsumme"))
    parts.append(engine_selftest(ctx))
    rc, out = ctx.run([sys.executable, "scripts/engine_diff.py", "findings"], ctx.root)
    if rc == 0:
        parts.append((PASS, "Differenz-Gate Korpus identisch"))
    elif rc == 1:
        parts.append((FAIL, "Differenz-Gate: Python und Engine weichen ab"))
    else:
        parts.append((UNMEASURED, "Differenz-Gate nicht gemessen (kein Binary oder Korpus)"))
    return parts


def k5(ctx: Ctx) -> list[Part]:
    rc, out = ruttla(ctx, "--self-test")
    if rc is None:
        parts: list[Part] = [(UNMEASURED, f"--self-test nicht gelaufen: {out[:120]}")]
    elif rc == 0:
        parts = [(PASS, "ruttla --self-test grün")]
    else:
        parts = [(FAIL, f"ruttla --self-test Exit {rc}")]
    parts.append(engine_selftest(ctx))
    parts.append((UNMEASURED, "Trefferquote je Regel und fix:-Belege: Präzisionsliste (R4) noch nicht definiert"))
    return parts


def k6(ctx: Ctx) -> list[Part]:
    parts: list[Part] = []
    rc, out = ctx.run([sys.executable, "scripts/gen_rule_docs.py", "--check"], ctx.root)
    if rc is None:
        parts.append((UNMEASURED, f"gen_rule_docs --check nicht gelaufen: {out[:120]}"))
    elif rc != 0:
        parts.append((FAIL, "docs/RULES.md veraltet (gen_rule_docs --check)"))
    rc, out = ctx.run(["git", "ls-files", "--", *INTERNAL_DOCS], ctx.root)
    if rc != 0:
        parts.append((UNMEASURED, "git ls-files nicht lesbar"))
    else:
        tracked = out.split()
        if tracked:
            parts.append((FAIL, f"{len(tracked)} interne Dokus im öffentlichen Baum, z. B. {', '.join(tracked[:3])}"))
    if not parts:
        parts.append((PASS, "generierte Doku aktuell, keine internen Planungsdokumente getrackt"))
    if not any((ctx.root / "tests").glob("test_doc*gate*.py")):
        parts.append((UNMEASURED, "Doku-Gate (R5-3: Schalter/Formate gegen Code) fehlt noch"))
    return parts


def k7(ctx: Ctx) -> list[Part]:
    parts: list[Part] = []
    wf = read(ctx, ".github/workflows/release.yml") or ""
    if not re.search(r"^\s{2}install[\w-]*:", wf, re.M):
        parts.append((FAIL, "Installationsjob (install*) fehlt in release.yml"))
    if "pypa/gh-action-pypi-publish" not in wf:
        parts.append((FAIL, "release.yml veröffentlicht nicht auf PyPI (R6-2)"))
    if not ctx.allow_network:
        parts.append(NO_NET)
        return parts
    status, body = ctx.fetch("https://pypi.org/pypi/ruttla/json")
    if status is None:
        parts.append((UNMEASURED, f"PyPI nicht erreichbar: {body[:100]}"))
    else:
        try:
            has = TARGET_VERSION in json.loads(body).get("releases", {}) if status == 200 else False
        except ValueError:
            has = False
        parts.append((PASS, f"ruttla {TARGET_VERSION} auf PyPI") if has
                     else (FAIL, f"ruttla {TARGET_VERSION} nicht auf PyPI (HTTP {status})"))
    ok, rel = gh_json(ctx, "release", "view", f"v{TARGET_VERSION}", "--json", "tagName")
    parts.append((PASS, f"GitHub-Release v{TARGET_VERSION} vorhanden") if ok
                 else (FAIL, f"GitHub-Release v{TARGET_VERSION} nicht lesbar: {rel}"))
    ok, runs = gh_json(ctx, "run", "list", "--workflow", "Release", "--branch", f"v{TARGET_VERSION}",
                       "--limit", "1", "--json", "status,conclusion")
    if not ok or not isinstance(runs, list):
        parts.append((UNMEASURED, f"Release-Lauf nicht lesbar: {runs}"))
    elif runs and runs[0].get("conclusion") == "success":
        parts.append((PASS, "Release-Lauf auf Tag inkl. Installationsjob (3 Systeme) grün"))
    else:
        parts.append((FAIL, "kein grüner Release-Lauf auf dem Tag"))
    return parts


def newest_audit(ctx: Ctx, prefix: str) -> dt.date | None:
    best: dt.date | None = None
    for path in (ctx.root / "docs" / "audits").glob(f"{prefix}_AUDIT_*.md"):
        m = re.search(r"(\d{4}-\d{2}-\d{2})\.md$", path.name)
        if m:
            try:
                day = dt.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            best = day if best is None or day > best else best
    return best


def k8(ctx: Ctx) -> list[Part]:
    parts: list[Part] = []
    for prefix, label in (("TRADEMARK", "Markenprüfung"), ("PROVENANCE", "Provenienzprüfung"),
                          ("HISTORY", "Historienprüfung")):
        day = newest_audit(ctx, prefix)
        if day is None:
            parts.append((FAIL, f"{label}: kein Bericht docs/audits/{prefix}_AUDIT_<Datum>.md"))
        elif (ctx.today - day).days > MAX_AUDIT_AGE_DAYS or day > ctx.today:
            parts.append((FAIL, f"{label}: Bericht vom {day} nicht aktuell (Grenze {MAX_AUDIT_AGE_DAYS} Tage)"))
    py, _ = versions(ctx)
    major = (py or TARGET_VERSION).split(".")[0]
    security = read(ctx, "SECURITY.md")
    if security is None:
        parts.append((FAIL, "SECURITY.md fehlt"))
    elif not re.search(rf"^\|\s*{re.escape(major)}\.[^|]*\|\s*yes", security, re.M | re.IGNORECASE):
        parts.append((FAIL, f"SECURITY.md nennt keine unterstützte Version {major}.x"))
    if not parts:
        parts.append((PASS, "drei Berichte aktuell, SECURITY.md nennt die Hauptversion"))
    return parts


def k9(ctx: Ctx) -> list[Part]:
    rc, out = ruttla(ctx, "--strict", "--format", "agent", ".")
    if rc == 0:
        return [(PASS, "strikter Selbstscan Exit 0")]
    if rc == 1:
        return [(FAIL, "strikter Selbstscan hat blockierende Befunde")]
    return [(UNMEASURED, f"strikter Selbstscan Exit {rc}: nichts gemessen oder Laufzeitfehler")]


CRITERIA = (
    ("K1", "CI auf main grün, dreimal in Folge", k1),
    ("K2", "Version 1.0.0 aus einer Quelle, keine Vorschau-Marker", k2),
    ("K3", "Öffentliche Verträge eingefroren und gesichert", k3),
    ("K4", "Engine: Binaries, Prüfsummen, Differenz-Gate", k4),
    ("K5", "Regelqualität: Selbsttest, Präzision", k5),
    ("K6", "Doku: generiert aktuell, nur Nutzerdoku öffentlich", k6),
    ("K7", "Verteilung: PyPI, GitHub-Release, Installation", k7),
    ("K8", "Recht und Sicherheit: Berichte, SECURITY.md", k8),
    ("K9", "Strikter Selbstscan Exit 0", k9),
)


def measure(ctx: Ctx, only: set[str] | None = None) -> list[Result]:
    results = []
    for key, title, fn in CRITERIA:
        if only is not None and key not in only:
            continue
        res = Result(key, title)
        try:
            res.parts = fn(ctx)
        except Exception as exc:  # Messfehler ist nie „bestanden“
            res.parts = [(UNMEASURED, f"Messfehler {type(exc).__name__}: {exc}")]
        results.append(res)
    return results


def exit_code(results: list[Result]) -> int:
    states = [r.status for r in results]
    if FAIL in states:
        return 1
    if UNMEASURED in states or not states:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO)
    ap.add_argument("--allow-network", action="store_true")
    ap.add_argument("--only", help="Kriterien, kommagetrennt, z. B. K2,K3")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    only = None
    if args.only:
        only = {k.strip().upper() for k in args.only.split(",") if k.strip()}
        unknown = only - {k for k, _, _ in CRITERIA}
        if unknown:
            print(f"Unbekanntes Kriterium: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 3
    if not args.root.is_dir():
        print(f"--root ist kein Verzeichnis: {args.root}", file=sys.stderr)
        return 3
    ctx = Ctx(args.root.resolve(), args.allow_network, dt.date.today(), real_run, real_fetch)
    results = measure(ctx, only)
    code = exit_code(results)
    if args.json:
        print(json.dumps({"exit": code, "criteria": [
            {"id": r.key, "title": r.title, "status": r.status,
             "parts": [{"status": s, "text": t} for s, t in r.parts]} for r in results]},
            ensure_ascii=False, indent=2))
        return code
    mark = {PASS: "✓", FAIL: "✗", UNMEASURED: "?"}
    for r in results:
        print(f"{mark[r.status]} {r.key} {r.title} — {r.status}")
        for state, text in r.parts:
            if state != PASS or r.status == PASS:
                print(f"    {mark[state]} {text}")
    counts = {s: sum(r.status == s for r in results) for s in (PASS, FAIL, UNMEASURED)}
    print(f"\n{counts[PASS]} bestanden · {counts[FAIL]} durchgefallen · {counts[UNMEASURED]} nicht gemessen")
    return code


if __name__ == "__main__":
    sys.exit(main())
