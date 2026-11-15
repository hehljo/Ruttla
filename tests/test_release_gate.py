"""scripts/release_gate.py: je Kriterium gesund → bestanden, kaputt → durchgefallen."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import REPO

_spec = importlib.util.spec_from_file_location("release_gate", REPO / "scripts" / "release_gate.py")
rg = importlib.util.module_from_spec(_spec)
sys.modules["release_gate"] = rg
_spec.loader.exec_module(rg)

TODAY = dt.date(2026, 12, 1)
IDS = ["a.one", "b.two"]
RELEASE_YML = """jobs:
  engine:
    strategy:
      matrix:
        include:
          - { os: a, target: x86_64-unknown-linux-musl }
          - { os: b, target: aarch64-unknown-linux-musl }
          - { os: c, target: aarch64-apple-darwin }
          - { os: d, target: x86_64-apple-darwin }
          - { os: e, target: x86_64-pc-windows-msvc }
    steps:
      - run: sha256sum x > SHA256SUMS
  install-smoke:
    runs-on: x
  pypi:
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
"""
CONTRACTS = "\n".join(f"| {k} |" for k in (
    "CLI flags", "Exit codes", "Profile", "JSON report", "Agent format", "SARIF", "Check IDs",
    "Rule format", "Self-test export", "Baseline", "Stats export"))
TESTS = "\n".join(f"def {n}" for n in (
    "test_exit_zero", "test_exit_one", "test_exit_two", "test_exit_three",
    "test_config_version", "test_new_profile_name_is_read", "test_agent_format_only_appends_fields"))


def healthy(root: Path, **over: str | None) -> None:
    files = {
        "src/ruttla/__init__.py": '__version__ = "1.0.0"\n',
        "engine/Cargo.toml": '[package]\nname = "x"\nversion = "1.0.0"\n',
        "pyproject.toml": 'classifiers = [\n"Development Status :: 5 - Production/Stable",\n]\n',
        "README.md": "stabil\n", "README.de.md": "stabil\n", "docs/A.md": "text\n",
        "docs/CONTRACTS.md": CONTRACTS, "tests/test_contracts.py": TESTS,
        "tests/golden/check_ids.txt": "\n".join(IDS),
        "tests/golden/cli_flags.txt": "x", "tests/golden/sarif_shape.json": "{}",
        "tests/golden/baseline_schema.json": "{}", "tests/golden/stats_export.json": "{}",
        "schemas/report.schema.json": "{}", "schemas/selftests.schema.json": "{}",
        "schemas/rule.schema.json": "{}",
        ".github/workflows/release.yml": RELEASE_YML,
        "install.sh": "sha256sum -c\n", "install.ps1": "Get-FileHash x\n",
        "tests/test_docs_gate.py": "",
        "SECURITY.md": "| Version | Supported |\n|---|---|\n| 1.x | yes |\n| 0.1.x | no |\n",
        "docs/audits/TRADEMARK_AUDIT_2026-11-20.md": "x",
        "docs/audits/PROVENANCE_AUDIT_2026-11-20.md": "x",
        "docs/audits/HISTORY_AUDIT_2026-11-20.md": "x",
    }
    files.update(over)
    for rel, text in files.items():
        path = root / rel
        if text is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class Fake:
    """Ersetzt Unterprozesse und Netz; Antworten je Kommandoanfang überschreibbar."""

    def __init__(self, **over):
        self.rc = {"ci": 0, "list": 0, "selftest": 0, "docs": 0, "git": 0, "scan": 0, "diff": 0, "engine": 0}
        self.rc.update(over.pop("rc", {}))
        self.ci_runs = over.pop("ci_runs", [{"status": "completed", "conclusion": "success"}] * 3)
        self.tracked = over.pop("tracked", "")
        self.pypi = over.pop("pypi", (200, json.dumps({"releases": {"1.0.0": []}})))
        self.release = over.pop("release", (0, '{"tagName": "v1.0.0"}'))
        self.rel_runs = over.pop("rel_runs", [{"status": "completed", "conclusion": "success"}])
        self.ids = over.pop("ids", IDS)
        self.calls: list[list[str]] = []

    def run(self, cmd, cwd):
        self.calls.append(cmd)
        joined = " ".join(cmd)
        if cmd[0].endswith("ruttla-engine"):
            return self.rc["engine"], ""
        if cmd[0] == "gh":
            if "release view" in joined:
                return self.release
            runs = self.ci_runs if "--workflow CI" in joined else self.rel_runs
            return self.rc["ci"], json.dumps(runs)
        if cmd[0] == "git":
            return self.rc["git"], self.tracked
        if "--list" in cmd:
            return self.rc["list"], json.dumps({"rules": [{"id": i} for i in self.ids]})
        if "--self-test" in cmd:
            return self.rc["selftest"], ""
        if cmd[1].endswith("gen_rule_docs.py"):
            return self.rc["docs"], ""
        if cmd[1].endswith("engine_diff.py"):
            return self.rc["diff"], ""
        if "--strict" in cmd:
            return self.rc["scan"], ""
        return None, "unbekannt"

    def fetch(self, url):
        return self.pypi


class GateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        healthy(self.root)

    def place_engine(self):
        """Attrappe eines gebauten Engine-Binaries (Pfad wie in release_gate.engine_binary)."""
        folder = self.root / "engine" / "target" / "release"
        folder.mkdir(parents=True)
        (folder / "ruttla-engine").write_text("x")

    def status(self, key, fake=None, network=True, today=TODAY):
        fake = fake or Fake()
        ctx = rg.Ctx(self.root, network, today, fake.run, fake.fetch)
        (res,) = rg.measure(ctx, {key})
        return res

    def assertStatus(self, key, want, text="", **kw):
        res = self.status(key, **kw)
        self.assertEqual(res.status, want, res.parts)
        if text:
            self.assertIn(text, " ".join(t for _, t in res.parts))

    def test_k1(self):
        self.assertStatus("K1", rg.PASS)
        bad = [{"status": "completed", "conclusion": "failure"}] + [{"status": "completed", "conclusion": "success"}] * 2
        self.assertStatus("K1", rg.FAIL, "2 von 3", fake=Fake(ci_runs=bad))
        self.assertStatus("K1", rg.FAIL, "nur 2", fake=Fake(ci_runs=bad[1:]))
        self.assertStatus("K1", rg.UNMEASURED, fake=Fake(rc={"ci": 1}))
        self.assertStatus("K1", rg.UNMEASURED, "allow-network", network=False)

    def test_k2(self):
        self.assertStatus("K2", rg.PASS)
        healthy(self.root, **{"src/ruttla/__init__.py": '__version__ = "1.0.0.dev0"\n'})
        self.assertStatus("K2", rg.FAIL, "__version__")
        healthy(self.root, **{"src/ruttla/__init__.py": '__version__ = "1.0.0"\n',
                              "engine/Cargo.toml": '[package]\nversion = "0.1.0"\n'})
        self.assertStatus("K2", rg.FAIL, "Cargo")
        healthy(self.root, **{"engine/Cargo.toml": '[package]\nversion = "1.0.0"\n',
                              "pyproject.toml": '"Development Status :: 4 - Beta",\n'})
        self.assertStatus("K2", rg.FAIL, "Classifier")
        healthy(self.root, **{"pyproject.toml": '"Development Status :: 5 - Production/Stable",\n',
                              "docs/A.md": "Status: Preview\n"})
        self.assertStatus("K2", rg.FAIL, "docs/A.md:1")

    def test_k3(self):
        self.assertStatus("K3", rg.PASS)
        healthy(self.root, **{"tests/golden/check_ids.txt": "a.one"})
        self.assertStatus("K3", rg.FAIL, "1 von 2 IDs")
        healthy(self.root, **{"tests/golden/check_ids.txt": "a.one\nb.two", "tests/golden/cli_flags.txt": None})
        self.assertStatus("K3", rg.FAIL, "CLI-Schalter")
        healthy(self.root, **{"tests/golden/cli_flags.txt": "x", "docs/CONTRACTS.md": CONTRACTS.replace("Baseline", "")})
        self.assertStatus("K3", rg.FAIL, "nicht genannt: Baseline")
        healthy(self.root, **{"docs/CONTRACTS.md": CONTRACTS, "tests/test_contracts.py": TESTS.replace("test_exit_two", "x")})
        self.assertStatus("K3", rg.FAIL, "Exit-Codes")
        healthy(self.root)
        self.assertStatus("K3", rg.UNMEASURED, fake=Fake(rc={"list": 1}))

    def test_k4(self):
        self.place_engine()
        self.assertStatus("K4", rg.PASS)
        self.assertStatus("K4", rg.FAIL, "selftest", fake=Fake(rc={"engine": 1}))
        self.assertStatus("K4", rg.FAIL, "weichen ab", fake=Fake(rc={"diff": 1}))
        self.assertStatus("K4", rg.UNMEASURED, fake=Fake(rc={"diff": 2}))
        healthy(self.root, **{".github/workflows/release.yml": RELEASE_YML.replace("target: x86_64-pc-windows-msvc", "")})
        self.assertStatus("K4", rg.FAIL, "4 Ziele")
        healthy(self.root, **{".github/workflows/release.yml": RELEASE_YML.replace("SHA256SUMS", "X")})
        self.assertStatus("K4", rg.FAIL, "SHA256SUMS")
        healthy(self.root, **{"install.sh": "curl\n"})
        self.assertStatus("K4", rg.FAIL, "install.sh")

    def test_k5(self):
        self.assertStatus("K5", rg.UNMEASURED, "Präzisionsliste")  # R4 fehlt ausdrücklich
        self.assertStatus("K5", rg.FAIL, "Exit 1", fake=Fake(rc={"selftest": 1}))

    def test_k6(self):
        res = self.status("K6")
        self.assertEqual(res.status, rg.PASS, res.parts)
        self.assertStatus("K6", rg.FAIL, "veraltet", fake=Fake(rc={"docs": 1}))
        self.assertStatus("K6", rg.FAIL, "STATUS.md", fake=Fake(tracked="STATUS.md\n"))
        (self.root / "tests/test_docs_gate.py").unlink()
        self.assertStatus("K6", rg.UNMEASURED, "R5-3")

    def test_k7(self):
        self.assertStatus("K7", rg.PASS)
        self.assertStatus("K7", rg.FAIL, "nicht auf PyPI", fake=Fake(pypi=(404, "")))
        self.assertStatus("K7", rg.FAIL, "Release v1.0.0", fake=Fake(release=(1, "nicht gefunden")))
        self.assertStatus("K7", rg.FAIL, "Release-Lauf", fake=Fake(rel_runs=[{"conclusion": "failure"}]))
        self.assertStatus("K7", rg.UNMEASURED, fake=Fake(pypi=(None, "offline")))
        self.assertStatus("K7", rg.UNMEASURED, "allow-network", network=False)
        healthy(self.root, **{".github/workflows/release.yml": RELEASE_YML.replace("pypa/gh-action-pypi-publish", "x")})
        self.assertStatus("K7", rg.FAIL, "PyPI (R6-2)", network=False)

    def test_k8(self):
        self.assertStatus("K8", rg.PASS)
        (self.root / "docs/audits/TRADEMARK_AUDIT_2026-11-20.md").unlink()
        self.assertStatus("K8", rg.FAIL, "Markenprüfung")
        healthy(self.root)
        self.assertStatus("K8", rg.FAIL, "nicht aktuell", today=dt.date(2027, 1, 30))
        healthy(self.root, **{"SECURITY.md": "| 0.1.x | yes |\n"})
        self.assertStatus("K8", rg.FAIL, "SECURITY.md")

    def test_k9(self):
        self.assertStatus("K9", rg.PASS)
        self.assertStatus("K9", rg.FAIL, fake=Fake(rc={"scan": 1}))
        self.assertStatus("K9", rg.UNMEASURED, fake=Fake(rc={"scan": 2}))
        self.assertStatus("K9", rg.UNMEASURED, fake=Fake(rc={"scan": 3}))

    def test_all_green_on_prepared_copy(self):
        self.place_engine()
        fake = Fake()
        ctx = rg.Ctx(self.root, True, TODAY, fake.run, fake.fetch)
        res = {r.key: r.status for r in rg.measure(ctx)}
        # K5 bleibt ehrlich offen, bis R4 die Präzisionsliste definiert
        self.assertEqual({k for k, v in res.items() if v != rg.PASS}, {"K5"}, res)
        self.assertEqual(rg.exit_code(rg.measure(ctx)), 2)

    def test_exit_codes(self):
        mk = lambda s: rg.Result("K", "t", [(s, "x")])  # noqa: E731
        self.assertEqual(rg.exit_code([mk(rg.PASS)]), 0)
        self.assertEqual(rg.exit_code([mk(rg.PASS), mk(rg.UNMEASURED)]), 2)
        self.assertEqual(rg.exit_code([mk(rg.UNMEASURED), mk(rg.FAIL)]), 1)
        self.assertEqual(rg.exit_code([]), 2)

    def test_measure_error_is_never_pass(self):
        def boom(cmd, cwd):
            raise RuntimeError("kaputt")
        ctx = rg.Ctx(self.root, False, TODAY, boom, lambda u: (None, ""))
        (res,) = rg.measure(ctx, {"K9"})
        self.assertEqual(res.status, rg.UNMEASURED)

    def test_cli_bad_arguments_exit_three(self):
        script = str(REPO / "scripts" / "release_gate.py")
        for args in (["--only", "K42"], ["--root", "/gibt/es/nicht"]):
            done = subprocess.run([sys.executable, script, *args], capture_output=True, text=True)
            self.assertEqual(done.returncode, 3, args)


if __name__ == "__main__":
    unittest.main()
