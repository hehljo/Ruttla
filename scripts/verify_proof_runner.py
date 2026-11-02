#!/usr/bin/env python3
"""Repeatable local evidence block; scans target sources, never runs target code.

python3 scripts/verify_proof_runner.py --reference PATH --historical-ref REF
Use --template PATH to byte-compare the externally installed runner fixture.
No model/network calls. Logs and source copies remain in the local evidence directory.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ruttla.config import Config  # noqa: E402
from ruttla.context import Context  # noqa: E402
from ruttla.contracts import CONTRACT_FILE  # noqa: E402

ID = "quality.contract_proof_without_runner_writer"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--historical-ref", required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path, required=True, help="Scratch parent outside this checkout")
    parser.add_argument("--final-only", action="store_true", help="Only final source/diff scans, after documentation edits")
    parser.add_argument("--targeted-only", action="store_true", help="Rule/template/real controls and source gates, without whole-suite repeat")
    args = parser.parse_args()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out = REPO / "build" / "qa" / ("proof-runner-" + stamp)
    out.mkdir(parents=True)
    temporary = args.temp_root.resolve() / stamp
    temporary.mkdir(parents=True)
    # A deliberately invalid local gitdir stops ancestor discovery. Tests that
    # initialize their own child Git tree still get a real isolated repository.
    (temporary / ".git").write_text("gitdir: .git-test-boundary-missing\n")
    git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    parent_repo = subprocess.run(["git", "-C", str(temporary), "rev-parse", "--show-toplevel"], env=git_env, capture_output=True, timeout=30)
    if temporary.is_relative_to(REPO):
        raise SystemExit("Test-Scratch muss außerhalb dieses Checkouts liegen")
    if parent_repo.returncode == 0:
        raise SystemExit("Git-Grenze für Test-Scratch ist unwirksam")
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"), TMPDIR=str(temporary),
               RUTTLA_STATS_DIR=str(out / "stats"), PYTHONDONTWRITEBYTECODE="1")
    rows = []

    def run(name, command, expected=0):
        with (out / (name + ".log")).open("w") as log:
            result = subprocess.run(command, cwd=REPO, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=1800)
        rows.append({"name": name, "exit": result.returncode, "expected": expected,
                     "command": [str(x) for x in command]})
        print(f"{name}: EXIT={result.returncode}, erwartet={expected}", flush=True)
        (out / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
        if name in {"engine-build", "focused", "template", "reference-current", "reference-historical"} and result.returncode != expected:
            (out / "summary.txt").write_text(f"ROT: {name} (Abnahmevorbedingung)\n")
            raise SystemExit(f"ROT: {name}; {out}")
        return result.returncode

    def scan(name, root, expected=None):
        command = [sys.executable, "master_gate.py", str(root), "--check", ID, "--strict", "--format", "json"]
        run(name, command, expected if expected is not None else [0, 1, 2])
        report = json.loads((out / (name + ".log")).read_text())
        rows[-1]["result"] = report["results"][0]
        return rows[-1]["exit"]

    if not args.final_only:
        fixture = REPO / "tests/fixtures/sammellauf_template/run_all_gates.sh"
        if fixture.read_bytes() != args.template.read_bytes():
            raise SystemExit("Template und geprüfte Fixture unterscheiden sich")
        run("engine-build", ["cargo", "build", "--offline", "--manifest-path", "engine/Cargo.toml"])
        run("focused", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_proof_runner.py", "-v"])
        run("template", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_sammellauf_template.py", "-v"])
        scan("reference-current", args.reference, 0)
        # Copy only the scanner's relevant source inventory, not private assets or
        # generated receipts. The historical runner bytes are read directly from Git.
        copy = out / "historical-source-copy"
        copy.mkdir()
        for sf in Context(str(args.reference), Config()).all_files():
            if sf.ext in {".sh", ".py", ".conf"} or Path(sf.rel).name == CONTRACT_FILE:
                dest = copy / sf.rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(sf.text)
        runner = "tools/run_all_gates.sh"
        old = subprocess.run(["git", "-C", str(args.reference), "show", args.historical_ref + ":" + runner],
                             env=env, capture_output=True, check=True, timeout=30)
        (copy / runner).write_bytes(old.stdout)
        scan("reference-historical", copy, 1)
        inventory = subprocess.run(["rg", "--files", "--hidden", "-g", CONTRACT_FILE,
                                    "/root", "--max-depth", "4"], capture_output=True, text=True, timeout=60)
        if inventory.returncode not in {0, 1}:
            raise SystemExit(f"Manifestinventar fehlgeschlagen: {inventory.stderr}")
        manifests = sorted(set(inventory.stdout.splitlines()))
        (out / "manifest-inventory.txt").write_text("\n".join(manifests) + "\n")
        for index, manifest in enumerate(manifests):
            root = Path(manifest).parent
            if root.resolve() != args.reference.resolve() and not root.is_relative_to(REPO):
                scan(f"foreign-{index:02d}", root)
        if not args.targeted_only:
            run("unittest", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
            run("engine-selftest", [str(REPO / "engine" / "target" / "debug" / "ruttla-engine"), "selftest", "--rules", "src/ruttla/rules"])
            run("self-test", [sys.executable, "master_gate.py", "--self-test"])
    run("rule-docs", [sys.executable, "scripts/gen_rule_docs.py", "--check"])
    run("strict", [sys.executable, "master_gate.py", ".", "--strict", "--format", "agent"])
    run("changed", [sys.executable, "master_gate.py", ".", "--changed-only", "--format", "agent"])
    run("diff", ["git", "diff", "--check"])
    (out / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    failed = [r["name"] for r in rows if r["exit"] not in (r["expected"] if isinstance(r["expected"], list) else [r["expected"]])]
    status = "ROT: " + ", ".join(failed) if failed else "GRÜN: alle erwarteten Ergebnisse"
    (out / "summary.txt").write_text(status + "\n")
    print(f"{status}\n{out}")
    return bool(failed)


if __name__ == "__main__":
    sys.exit(main())
