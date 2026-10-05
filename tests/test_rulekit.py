"""Konformitäts-Kit ``ruttla rule test`` (P10-T009).

Beide Richtungen: jede offizielle Regel wird angenommen (ein Kit, das gesunde
Regeln ablehnt, tötet gute Arbeit), und jede bösartige Testregel wird
abgelehnt — einzeln, an genau dem Prüfschritt, der sie betrifft.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from _support import REPO, SRC, engine_binary, require_engine

from ruttla.declarative import read_rules, rules_dir
from ruttla.rulekit import ACCEPTED, OK, REJECTED, dump_toml

HEALTHY = {
    "format": "ruttla-rule/0",
    "id": "demo.print_call",
    "title": "print im Code",
    "platform": "python",
    "severity": "warning",
    "scope": {"extensions": [".py"], "unit_label": "Python-Dateien"},
    "match": {
        "pattern": r"\bprint\(",
        "message": "print gefunden",
        "exclude": [{"on": "path", "pattern": r"(^|/)cli\.py$"}],
    },
    "fixtures": [
        {"name": "rot", "expect": "fail", "files": {"app.py": "print('x')\n"}},
        {"name": "grün", "expect": "pass", "files": {"app.py": "log.info('x')\n"}},
        {"name": "Ausschluss cli.py", "expect": "pass", "files": {"cli.py": "print('x')\n"}},
    ],
}


def _variant(**changes) -> dict:
    rule = copy.deepcopy(HEALTHY)
    for dotted, value in changes.items():
        *parents, key = dotted.split("__")
        target = rule
        for p in parents:
            target = target[p]
        if value is None:
            del target[key]
        else:
            target[key] = value
    return rule


# Name → (Regel, Prüfschritt, der ablehnen muss)
MALICIOUS: dict[str, tuple[dict, str]] = {
    # Klassisches ReDoS braucht Rückverweis/Lookaround — die Engine lädt es nicht.
    "redos_rueckverweis": (_variant(match__pattern=r"(\w+\s?)+\1"), "schema"),
    "redos_lookahead": (_variant(match__pattern=r"(?=(a+)+b)print\("), "schema"),
    "zu_grosses_muster": (_variant(match__pattern=r"\w{1000}{1000}"), "schema"),
    "ohne_gruene_fixture": (_variant(fixtures=HEALTHY["fixtures"][:1]), "schema"),
    "id_kollision": (_variant(id="web.hardcoded_endpoint", platform="web",
                              scope={"extensions": [".py"], "unit_label": "x"}), "id"),
    # Endung und Fixture-Pfad werden zu Dateinamen — unter Windows sind
    # `..\\` und `C:` Ausbrüche aus dem Arbeitsordner.
    "pfad_in_endung": (_variant(scope={"extensions": [".py/../../../x.py"], "unit_label": "x"}), "schema"),
    "pfad_in_fixture": (_variant(fixtures=[
        HEALTHY["fixtures"][0],
        {"name": "grün", "expect": "pass", "files": {"..\\..\\x.py": "log.info('x')\n"}},
        HEALTHY["fixtures"][2],
    ]), "schema"),
    "falsche_fixture": (_variant(fixtures=[
        HEALTHY["fixtures"][0],
        {"name": "grün?", "expect": "pass", "files": {"app.py": "print('x')\n"}},
    ]), "fixtures"),
    # Die Fixtures sind auch ohne den Ausschluss grün: der Ausschluss ist eine
    # ungeprüfte Freistellung.
    "toter_ausschluss": (_variant(fixtures=HEALTHY["fixtures"][:2]), "wirksamkeit"),
    # Trifft jedes Zeichen: linear, aber eine Befundflut.
    "befundflut": (_variant(match__pattern=r"[\s\S]", match__exclude=None, fixtures=[
        {"name": "rot", "expect": "fail", "files": {"app.py": "x = 1\n"}},
        {"name": "grün", "expect": "pass", "files": {"app.py": ""}},
    ]), "budget"),
}


def _kit(*paths: Path, cwd: Path) -> tuple[int, dict]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    binary = engine_binary()
    if binary is not None:
        env["RUTTLA_ENGINE_BIN"] = str(binary)
    proc = subprocess.run([sys.executable, "-m", "ruttla", "rule", "test", *map(str, paths),
                           "--format", "json"], cwd=cwd, env=env, text=True, encoding="utf-8",
                          capture_output=True, timeout=600)
    return proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else {"stderr": proc.stderr}


def _steps(report: dict) -> dict[str, str]:
    return {s["step"]: s["status"] for s in report["steps"]}


class TomlWriter(unittest.TestCase):
    def test_every_official_rule_round_trips(self) -> None:
        rules = read_rules()
        self.assertGreaterEqual(len(rules), 5)
        for rule in rules:
            with self.subTest(rule=rule["id"]):
                self.assertEqual(tomllib.loads(dump_toml(rule)), rule)

    def test_control_characters_and_quotes(self) -> None:
        data = {"a": "x\"y\\z\x00\x1f\x7f\f ü", "files": {"dir/a b.py": "1"}}
        self.assertEqual(tomllib.loads(dump_toml(data)), data)


class Kit(unittest.TestCase):
    def setUp(self) -> None:
        require_engine(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, directory: Path, rule: dict) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{rule['id']}.toml"
        path.write_text(dump_toml(rule), encoding="utf-8")
        return path

    def test_official_rules_are_accepted(self) -> None:
        code, data = _kit(rules_dir(), cwd=self.tmp)
        self.assertEqual(code, 0, data)
        self.assertEqual(len(data["rules"]), len(read_rules()))
        for report in data["rules"]:
            self.assertEqual(report["verdict"], ACCEPTED, report)

    def test_healthy_rule_outside_the_repo_is_accepted(self) -> None:
        path = self._write(self.tmp / "paket", HEALTHY)
        self.assertFalse(path.resolve().is_relative_to(REPO))
        code, data = _kit(path, cwd=self.tmp)
        self.assertEqual(code, 0, data)
        self.assertEqual(set(_steps(data["rules"][0]).values()), {OK})

    def test_each_malicious_rule_is_rejected_at_its_own_step(self) -> None:
        paths = {}
        for name, (rule, _) in MALICIOUS.items():
            if name != "id_kollision":
                # Eigene ID je Regel: ein Aufruf ist ein Paket, Dubletten darin
                # wären ein zweiter Befund.
                rule = {**rule, "id": f"demo.{name}"}
            paths[name] = self._write(self.tmp / name, rule)
        code, data = _kit(*paths.values(), cwd=self.tmp)
        self.assertEqual(code, 1, data)
        by_path = {Path(r["path"]).parent.name: r for r in data["rules"]}
        for name, (_, step) in MALICIOUS.items():
            with self.subTest(rule=name):
                report = by_path[name]
                steps = _steps(report)
                self.assertEqual(report["verdict"], REJECTED, report)
                self.assertEqual(steps[step], REJECTED, report)
                # Einzeln: kein anderer Schritt lehnt ab — sonst ist nicht
                # belegt, dass genau dieser Schritt den Fall fängt.
                others = {k: v for k, v in steps.items() if k != step and v == REJECTED}
                self.assertEqual(others, {}, report)

    def test_crlf_rule_file_is_accepted(self) -> None:
        # Windows-Checkout/Editor: CRLF muss die Isolation unverändert überstehen.
        path = self.tmp / "crlf" / f"{HEALTHY['id']}.toml"
        path.parent.mkdir()
        path.write_bytes(dump_toml(HEALTHY).replace("\n", "\r\n").encode("utf-8"))
        code, data = _kit(path, cwd=self.tmp)
        self.assertEqual(code, 0, data)

    def test_duplicate_id_inside_a_package(self) -> None:
        self._write(self.tmp / "paket" / "a", HEALTHY)
        self._write(self.tmp / "paket" / "b", HEALTHY)
        code, data = _kit(self.tmp / "paket", cwd=self.tmp)
        self.assertEqual(code, 1, data)
        self.assertEqual([_steps(r)["id"] for r in data["rules"]], [REJECTED, REJECTED])

    def test_official_file_itself_is_no_collision(self) -> None:
        official = next(rules_dir().rglob("web.hardcoded_endpoint.toml"))
        code, data = _kit(official, cwd=self.tmp)
        self.assertEqual(code, 0, data)

    def test_no_rule_found_is_not_green(self) -> None:
        (self.tmp / "leer").mkdir()
        env = dict(os.environ, PYTHONPATH=str(SRC))
        proc = subprocess.run([sys.executable, "-m", "ruttla", "rule", "test", str(self.tmp / "leer")],
                              cwd=self.tmp, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 3, proc.stderr)


class WithoutEngine(unittest.TestCase):
    def test_missing_engine_is_not_measured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{HEALTHY['id']}.toml"
            path.write_text(dump_toml(HEALTHY), encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(SRC), RUTTLA_ENGINE="off")
            env.pop("RUTTLA_ENGINE_BIN", None)
            proc = subprocess.run([sys.executable, "-m", "ruttla", "rule", "test", str(path),
                                   "--format", "json"], cwd=tmp, env=env, capture_output=True,
                                  text=True, encoding="utf-8", timeout=60)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)["rules"][0]
            self.assertEqual(report["verdict"], "nicht gemessen")
            self.assertNotIn(REJECTED, _steps(report).values())


if __name__ == "__main__":
    unittest.main()
