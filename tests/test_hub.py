"""Gate-Hub v0 (P10-T010): Paketformat, Signatur-/Hash-Pflicht, Lockfile, Scan.

Jede Ablehnung der Abnahme hat einen eigenen Testfall, der die vorherigen
Stufen ausdrücklich passieren lässt: manipuliert (Hash), unsigniert,
falsch-positiv. Netz gibt es hier nicht — ``hub._fetch`` wird ersetzt, die
echte Signatur prüft der Ende-zu-Ende-Lauf gegen das Index-Repo.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO, SRC, ensure_checks_loaded, require_engine

from ruttla import hub
from ruttla.declarative import read_rules
from ruttla.engine import EXIT_CRASH, EXIT_FAILED, EXIT_OK, EXIT_UNMEASURED
from ruttla.registry import REGISTRY

RULE = """\
format = "ruttla-rule/0"
id = "hub.demo.todo_marker"
title = "TODO-Marker im Skript"
platform = "universal"
severity = "warning"

[scope]
extensions = [".sh"]
unit_label = "Shell-Dateien"
skip_comments = false

[match]
per_line = true
pattern = 'TODO-HUB'
message = "Marker gefunden"

[[fixtures]]
name = "rot"
expect = "fail"
[fixtures.files]
"a.sh" = "# TODO-HUB\\n"

[[fixtures]]
name = "grün"
expect = "pass"
[fixtures.files]
"a.sh" = "echo ok\\n"
"""

META = {
    "format": hub.PACKAGE_FORMAT, "name": "demo", "version": "1.0.0",
    "description": "Demo-Paket", "evidence": ["https://example.org/issue/1"], "license": "MIT",
}


def package(**overrides) -> dict:
    return {**META, "rules": {"universal/hub.demo.todo_marker.toml": RULE}, **overrides}


def write_source(root: Path, pkg: dict) -> Path:
    d = root / pkg["name"]
    (d / "rules").mkdir(parents=True)
    meta = "\n".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in pkg.items() if k != "rules")
    (d / "package.toml").write_text(meta + "\n", encoding="utf-8", newline="\n")
    for rel, text in pkg["rules"].items():
        p = d / "rules" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")  # Hash gilt den Bytes, auch unter Windows
    return d


class FakeHub:
    """Release-Assets im Speicher; ``None`` = 404."""

    def __init__(self, pkg: dict, *, signed: bool = True, index_sha: str | None = None):
        self.raw = hub.canonical(pkg)
        sha = index_sha or hub.sha256(self.raw)
        fname = hub.package_file(pkg["name"], pkg["version"])
        self.assets = {
            hub.INDEX_FILE: json.dumps({"format": hub.INDEX_FORMAT, "packages": {
                pkg["name"]: {"version": pkg["version"], "sha256": sha, "description": "x",
                              "versions": {pkg["version"]: sha}}}}).encode(),
            fname: self.raw,
        }
        if signed:
            self.assets[fname + hub.BUNDLE_SUFFIX] = b'{"bundle": "fake"}'

    def __call__(self, name: str) -> bytes | None:
        return self.assets.get(name)


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class PackageFormatTest(TempCase):
    def test_canonical_roundtrip(self) -> None:
        raw = hub.canonical(package())
        self.assertEqual(hub.parse_package(raw), package())

    def test_non_canonical_bytes_rejected(self) -> None:
        raw = json.dumps(package(), indent=2).encode()
        with self.assertRaisesRegex(hub.HubError, "kanonisch"):
            hub.parse_package(raw)

    def test_each_invalid_field_rejected(self) -> None:
        cases = {
            "ohne hub-Namensraum": package(rules={"universal/demo.todo.toml": RULE.replace(
                "hub.demo.todo_marker", "demo.todo")}),
            "fremder Paketnamensraum": package(rules={"universal/hub.other.todo_marker.toml": RULE.replace(
                "hub.demo.todo_marker", "hub.other.todo_marker")}),
            "Pfad-Traversal": package(rules={"../hub.demo.todo_marker.toml": RULE}),
            "Plattform ≠ Verzeichnis": package(rules={"web/hub.demo.todo_marker.toml": RULE}),
            "id ≠ Dateiname": package(rules={"universal/hub.demo.other.toml": RULE}),
            "ohne Beleg": package(evidence=[]),
            "Beleg ohne https": package(evidence=["http://example.org"]),
            "Zusatzfeld": {**package(), "postinstall": "rm -rf /"},
            "Version": package(version="1.0"),
            "Name": package(name="Demo-Paket"),
            "ohne Regeln": package(rules={}),
        }
        for label, pkg in cases.items():
            with self.subTest(label):
                self.assertTrue(hub.validate_package(pkg), label)

    def test_healthy_package_valid(self) -> None:
        self.assertEqual(hub.validate_package(package()), [])

    def test_read_source_matches_canonical_form(self) -> None:
        d = write_source(self.tmp, package())
        self.assertEqual(hub.read_source(d), package())


class BuildIndexTest(TempCase):
    def test_build_writes_package_and_index(self) -> None:
        write_source(self.tmp / "src", package())
        written = hub.build_index(self.tmp / "src", self.tmp / "out", None)
        self.assertEqual(written, ["demo-1.0.0.json"])
        raw = (self.tmp / "out" / "demo-1.0.0.json").read_bytes()
        index = json.loads((self.tmp / "out" / "index.json").read_text())
        self.assertEqual(index["packages"]["demo"]["sha256"], hub.sha256(raw))

    def test_published_version_is_immutable(self) -> None:
        write_source(self.tmp / "src", package())
        prev = {"packages": {"demo": {"version": "1.0.0", "sha256": "0" * 64,
                                      "versions": {"1.0.0": "0" * 64}}}}
        with self.assertRaisesRegex(hub.HubError, "Version erhöhen"):
            hub.build_index(self.tmp / "src", self.tmp / "out", prev)

    def test_same_content_same_version_is_fine(self) -> None:
        write_source(self.tmp / "src", package())
        digest = hub.sha256(hub.canonical(package()))
        prev = {"packages": {"demo": {"version": "1.0.0", "sha256": digest, "versions": {"1.0.0": digest}}}}
        self.assertEqual(hub.build_index(self.tmp / "src", self.tmp / "out", prev), ["demo-1.0.0.json"])


class AddSyncTest(TempCase):
    def setUp(self) -> None:
        super().setUp()
        ensure_checks_loaded()

    def _add(self, fake: FakeHub, verify=lambda raw, bundle: None) -> str:
        with mock.patch.object(hub, "_fetch", fake), mock.patch.object(hub, "verify_signature", verify):
            return hub.add(self.tmp, "demo")

    def test_add_writes_lock_and_store(self) -> None:
        self._add(FakeHub(package()))
        lock = hub.read_lock(self.tmp)
        self.assertEqual(lock["demo"]["sha256"], hub.sha256(hub.canonical(package())))
        stored = (self.tmp / hub.STORE / "demo" / hub.PACKAGE_FILE).read_bytes()
        self.assertEqual(stored, hub.canonical(package()))

    def test_unsigned_package_rejected_nothing_written(self) -> None:
        # Echte Prüffunktion: sie muss am fehlenden Bundle scheitern, vor sigstore.
        fake = FakeHub(package(), signed=False)
        with mock.patch.object(hub, "_fetch", fake):
            with self.assertRaisesRegex(hub.HubError, "nicht signiert"):
                hub.add(self.tmp, "demo")
        self.assertFalse((self.tmp / hub.LOCKFILE).exists())
        self.assertFalse((self.tmp / hub.STORE).exists())

    def test_manipulated_download_rejected(self) -> None:
        with self.assertRaisesRegex(hub.HubError, "Hash"):
            self._add(FakeHub(package(), index_sha="f" * 64))
        self.assertFalse((self.tmp / hub.LOCKFILE).exists())

    def test_bad_signature_rejected(self) -> None:
        def reject(raw, bundle):
            raise hub.HubError("Signatur ungültig — abgelehnt: falscher Signierer")

        with self.assertRaisesRegex(hub.HubError, "Signatur ungültig"):
            self._add(FakeHub(package()), verify=reject)
        self.assertFalse((self.tmp / hub.LOCKFILE).exists())

    def test_sync_restores_deleted_store_and_remove_cleans_up(self) -> None:
        fake = FakeHub(package())
        self._add(fake)
        stored = self.tmp / hub.STORE / "demo" / hub.PACKAGE_FILE
        stored.unlink()
        with mock.patch.object(hub, "_fetch", fake), mock.patch.object(hub, "verify_signature",
                                                                      lambda r, b: None):
            self.assertEqual(hub.sync(self.tmp), ["demo 1.0.0: geladen und geprüft"])
        self.assertEqual(stored.read_bytes(), fake.raw)
        hub.remove(self.tmp, "demo")
        self.assertFalse((self.tmp / hub.LOCKFILE).exists())
        self.assertFalse((self.tmp / hub.STORE / "demo").exists())


class SymlinkTest(TempCase):
    """Ein Link im Prüfziel darf add/sync/remove nicht aus dem Projekt führen."""

    def setUp(self) -> None:
        super().setUp()
        ensure_checks_loaded()
        self.project = self.tmp / "projekt"
        self.outside = self.tmp / "draussen"
        self.project.mkdir()
        (self.outside / "hub" / "demo").mkdir(parents=True)
        (self.outside / "hub" / "demo" / "wichtig.txt").write_text("bleibt", encoding="utf-8")
        try:
            (self.project / ".ruttla").symlink_to(self.outside, target_is_directory=True)
        except OSError:
            self.skipTest("symbolische Links hier nicht anlegbar — nicht gemessen")

    def test_add_through_link_aborts(self) -> None:
        with mock.patch.object(hub, "_fetch", FakeHub(package())), \
                mock.patch.object(hub, "verify_signature", lambda r, b: None):
            with self.assertRaisesRegex(hub.HubError, "symbolischer Link"):
                hub.add(self.project, "demo")
        self.assertFalse((self.outside / "hub" / "demo" / hub.PACKAGE_FILE).exists())

    def test_remove_through_link_keeps_outside(self) -> None:
        hub.write_lock(self.project, {"demo": {"version": "1.0.0", "sha256": "0" * 64}})
        with self.assertRaisesRegex(hub.HubError, "symbolischer Link"):
            hub.remove(self.project, "demo")
        self.assertTrue((self.outside / "hub" / "demo" / "wichtig.txt").exists())

    def test_linked_lockfile_aborts(self) -> None:
        target = self.outside / "fremd.json"
        target.write_text("{}", encoding="utf-8")
        (self.project / ".ruttla").unlink()
        (self.project / hub.LOCKFILE).symlink_to(target)
        with self.assertRaisesRegex(hub.HubError, "symbolischer Link"):
            hub.write_lock(self.project, {"demo": {"version": "1.0.0", "sha256": "0" * 64}})
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")


class SignatureTest(unittest.TestCase):
    def test_without_sigstore_nothing_is_installed(self) -> None:
        with mock.patch.dict(sys.modules, {"sigstore": None, "sigstore.errors": None,
                                           "sigstore.models": None, "sigstore.verify": None}):
            with self.assertRaisesRegex(hub.HubError, "pip install"):
                hub.verify_signature(b"x", b"{}")

    def test_garbage_bundle_rejected(self) -> None:
        try:
            import sigstore  # noqa: F401
        except ImportError:
            self.skipTest("sigstore nicht installiert — nicht gemessen")
        with self.assertRaisesRegex(hub.HubError, "Signatur ungültig"):
            hub.verify_signature(b"x", b'{"mediaType": "kaputt"}')

    def test_requirement_matches_extra(self) -> None:
        extra = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["optional-dependencies"]["hub"]
        self.assertEqual(extra, [hub.SIGSTORE_REQUIREMENT])


class ScanTest(TempCase):
    """Der Scan lädt Hub-Regeln offline und nur bei passendem Hash."""

    def setUp(self) -> None:
        super().setUp()
        self.engine = require_engine(self)
        (self.tmp / "run.sh").write_text("echo TODO-HUB\n", encoding="utf-8")
        raw = hub.canonical(package())
        store = self.tmp / hub.STORE / "demo"
        store.mkdir(parents=True)
        (store / hub.PACKAGE_FILE).write_bytes(raw)
        hub.write_lock(self.tmp, {"demo": {"version": "1.0.0", "sha256": hub.sha256(raw)}})

    def _scan(self) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, PYTHONPATH=str(SRC), RUTTLA_ENGINE_BIN=str(self.engine))
        return subprocess.run([sys.executable, "-m", "ruttla", str(self.tmp), "--check", "hub.*",
                               "--format", "json"], env=env, text=True, encoding="utf-8",
                              capture_output=True, timeout=300)

    def test_installed_rule_runs(self) -> None:
        proc = self._scan()
        # Warnung ohne Profil ist nicht blockierend (Exit 0) — gemessen wird der Befund.
        self.assertEqual(proc.returncode, EXIT_OK, proc.stdout[-2000:] + proc.stderr[-2000:])
        result = {r["check_id"]: r for r in json.loads(proc.stdout)["results"]}["hub.demo.todo_marker"]
        self.assertEqual(result["status"], "fail")
        self.assertEqual([f["file"] for f in result["findings"]], ["run.sh"])

    def test_tampered_store_aborts(self) -> None:
        stored = self.tmp / hub.STORE / "demo" / hub.PACKAGE_FILE
        stored.write_bytes(stored.read_bytes().replace(b"TODO-HUB", b"TODO-XXX"))
        proc = self._scan()
        self.assertEqual(proc.returncode, EXIT_CRASH)
        self.assertIn("hub_lock_mismatch", proc.stdout + proc.stderr)

    def test_missing_store_aborts(self) -> None:
        (self.tmp / hub.STORE / "demo" / hub.PACKAGE_FILE).unlink()
        proc = self._scan()
        self.assertEqual(proc.returncode, EXIT_CRASH)
        self.assertIn("hub sync", proc.stdout + proc.stderr)


class EngineMultiRulesTest(TempCase):
    def test_same_id_in_two_directories_aborts(self) -> None:
        engine = require_engine(self)
        for d in ("a", "b"):
            p = self.tmp / d / "universal" / "hub.demo.todo_marker.toml"
            p.parent.mkdir(parents=True)
            p.write_text(RULE, encoding="utf-8")
        (self.tmp / "ziel").mkdir()
        proc = subprocess.run([str(engine), "scan", str(self.tmp / "ziel"), "--rules", str(self.tmp / "a"),
                               "--rules", str(self.tmp / "b")], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("kommt in", proc.stdout)


class CheckSourceTest(TempCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine = require_engine(self)
        self.pkg = write_source(self.tmp / "src", package())
        self.healthy = self.tmp / "gesund"
        self.healthy.mkdir()
        (self.healthy / "ok.sh").write_text("echo ok\n", encoding="utf-8")

    def _check(self, corpus: list[Path]) -> tuple[int, list[str]]:
        with mock.patch.dict(os.environ, {"RUTTLA_ENGINE_BIN": str(self.engine)}):
            return hub.check_source(self.pkg, corpus)

    def test_healthy_package_accepted(self) -> None:
        code, lines = self._check([self.healthy])
        self.assertEqual(code, EXIT_OK, "\n".join(lines))

    def test_false_positive_rejected(self) -> None:
        (self.healthy / "legit.sh").write_text("echo TODO-HUB ist hier legitim\n", encoding="utf-8")
        code, lines = self._check([self.healthy])
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn("Gesund-Korpus", "\n".join(lines))

    def test_no_corpus_is_not_measured(self) -> None:
        code, _ = self._check([])
        self.assertEqual(code, EXIT_UNMEASURED)

    def test_corpus_without_matching_files_is_not_measured(self) -> None:
        (self.healthy / "ok.sh").unlink()
        (self.healthy / "readme.txt").write_text("x\n", encoding="utf-8")
        code, lines = self._check([self.healthy])
        self.assertEqual(code, EXIT_UNMEASURED, "\n".join(lines))


class NamespaceTest(unittest.TestCase):
    def test_no_official_check_uses_hub_namespace(self) -> None:
        ensure_checks_loaded()
        official = [cid for cid, c in REGISTRY.items() if cid.startswith("hub.")
                    and not any(t.startswith("hub:") for t in c.tags)]
        self.assertEqual(official, [])
        self.assertFalse([r["id"] for r in read_rules() if r["id"].startswith("hub.")])

    def test_default_exclude_dirs_identical_in_python_and_engine(self) -> None:
        from ruttla.discovery import DEFAULT_EXCLUDE_DIRS

        rust = (REPO / "engine" / "src" / "inventory.rs").read_text(encoding="utf-8")
        block = re.search(r"DEFAULT_EXCLUDE_DIRS: &\[&str\] = &\[(.*?)\];", rust, re.S)
        self.assertIsNotNone(block)
        self.assertEqual(set(re.findall(r'"([^"]+)"', block.group(1))), DEFAULT_EXCLUDE_DIRS)
        self.assertIn(".ruttla", DEFAULT_EXCLUDE_DIRS)


if __name__ == "__main__":
    unittest.main()
