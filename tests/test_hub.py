"""Gate-Hub v0 (P10-T010): Paketformat, Signatur-/Hash-Pflicht, Lockfile, Scan.

Jede Ablehnung der Abnahme hat einen eigenen Testfall, der die vorherigen
Stufen ausdrücklich passieren lässt: manipuliert (Hash), unsigniert,
falsch-positiv. Netz gibt es hier nicht — ``hub._fetch`` wird ersetzt, die
echte Signatur prüft der Ende-zu-Ende-Lauf gegen das Index-Repo.
"""

from __future__ import annotations

import contextlib
import io
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

    def test_older_version_than_published_aborts(self) -> None:
        write_source(self.tmp / "src", package())
        prev = {"packages": {"demo": {"version": "1.2.0", "sha256": "0" * 64,
                                      "versions": {"1.2.0": "0" * 64}}}}
        with self.assertRaisesRegex(hub.HubError, "älter als die veröffentlichte 1.2.0"):
            hub.build_index(self.tmp / "src", self.tmp / "out", prev)
        # 1.10.0 ist neuer als 1.9.0 — numerisch verglichen, nicht als Text.
        write_source(self.tmp / "src2", package(version="1.10.0"))
        prev["packages"]["demo"].update(version="1.9.0", versions={"1.9.0": "0" * 64})
        self.assertEqual(hub.build_index(self.tmp / "src2", self.tmp / "out", prev), ["demo-1.10.0.json"])

    def test_malformed_previous_index_aborts(self) -> None:
        write_source(self.tmp / "src", package())
        for prev in ([], {"packages": []}, {"packages": {"demo": "x"}},
                     {"packages": {"demo": {"version": "../x", "sha256": "0" * 64}}}):
            with self.assertRaisesRegex(hub.HubError, "bisheriger Index"):
                hub.build_index(self.tmp / "src", self.tmp / "out", prev)

    def test_unreadable_previous_file_is_runner_error(self) -> None:
        write_source(self.tmp / "src", package())
        bad = self.tmp / "prev.json"
        bad.write_text("{kaputt", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = hub.run_hub_command(["build", str(self.tmp / "src"), str(self.tmp / "out"),
                                        "--previous", str(bad)])
        self.assertEqual(code, EXIT_CRASH)
        self.assertIn("nicht lesbar", err.getvalue())

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

    def test_invalid_index_entry_rejected_before_download(self) -> None:
        fake = FakeHub(package())
        index = json.loads(fake.assets[hub.INDEX_FILE])
        index["packages"]["demo"]["version"] = "../../evil"
        fake.assets[hub.INDEX_FILE] = json.dumps(index).encode()
        requested: list[str] = []
        with self.assertRaisesRegex(hub.HubError, "Index-Eintrag 'demo' ungültig"):
            self._add(lambda name: requested.append(name) or fake(name))
        self.assertEqual(requested, [hub.INDEX_FILE])
        self.assertFalse((self.tmp / hub.LOCKFILE).exists())

    def test_lock_with_invalid_version_rejected(self) -> None:
        (self.tmp / hub.LOCKFILE).write_text(json.dumps({"format": hub.LOCK_FORMAT, "packages": {
            "demo": {"version": "../../evil", "sha256": "0" * 64}}}), encoding="utf-8")
        with self.assertRaisesRegex(hub.HubError, "Eintrag 'demo' ungültig"):
            hub.read_lock(self.tmp)

    def test_search_skips_malformed_entries(self) -> None:
        fake = FakeHub(package())
        index = json.loads(fake.assets[hub.INDEX_FILE])
        index["packages"]["kaputt"] = "kein Objekt"
        fake.assets[hub.INDEX_FILE] = json.dumps(index).encode()
        out = io.StringIO()
        with mock.patch.object(hub, "_fetch", fake), contextlib.redirect_stdout(out):
            code = hub.run_hub_command(["search"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("demo 1.0.0", out.getvalue())
        self.assertNotIn("kaputt", out.getvalue())

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

    def test_install_hint_respects_pep668(self) -> None:
        plain = hub.sigstore_install_hint("/venv/bin/python", externally_managed=False)
        self.assertIn("/venv/bin/python -m pip install 'sigstore", plain)
        self.assertNotIn("--break-system-packages", plain)
        managed = hub.sigstore_install_hint("/usr/bin/python3", externally_managed=True)
        self.assertIn("PEP 668", managed)
        self.assertIn("venv", managed)
        self.assertIn("/usr/bin/python3 -m pip install --break-system-packages 'sigstore", managed)

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


def named(name: str, **overrides) -> dict:
    """Gültiges Paket unter anderem Namen — die Regel-ID zieht mit."""
    return package(name=name, rules={f"universal/hub.{name}.todo_marker.toml":
                                     RULE.replace("hub.demo.", f"hub.{name}.")}, **overrides)


class StoreGuardTest(TempCase):
    """Ein lokal verändertes Paket wird nie still überschrieben oder gelöscht."""

    def setUp(self) -> None:
        super().setUp()
        ensure_checks_loaded()
        self.fake = FakeHub(package())
        with mock.patch.object(hub, "_fetch", self.fake), \
                mock.patch.object(hub, "verify_signature", lambda raw, bundle: None):
            hub.add(self.tmp, "demo")
        self.stored = self.tmp / hub.STORE / "demo" / hub.PACKAGE_FILE
        self.edited = self.stored.read_bytes().replace(b"Demo-Paket", b"Demo-Paket, von Hand")
        self.stored.write_bytes(self.edited)

    def _call(self, fn, *args, **kwargs):
        requested: list[str] = []
        fetch = lambda name: requested.append(name) or self.fake(name)  # noqa: E731
        with mock.patch.object(hub, "_fetch", fetch), \
                mock.patch.object(hub, "verify_signature", lambda raw, bundle: None):
            return fn(self.tmp, *args, **kwargs), requested

    def _backup(self) -> Path:
        return self.tmp / hub.BACKUP / f"demo-{hub.sha256(self.edited)[:12]}.json"

    def test_sync_refuses_before_any_download(self) -> None:
        with self.assertRaisesRegex(hub.HubError, "lokal verändert, nicht überschrieben: demo"):
            self._call(hub.sync)
        self.assertEqual(self.stored.read_bytes(), self.edited)

    def test_sync_names_every_modified_package(self) -> None:
        raw = hub.canonical(named("zwei"))
        store = self.tmp / hub.STORE / "zwei"
        store.mkdir(parents=True)
        (store / hub.PACKAGE_FILE).write_bytes(raw + b" ")
        lock = hub.read_lock(self.tmp)
        lock["zwei"] = {"version": "1.0.0", "sha256": hub.sha256(raw)}
        hub.write_lock(self.tmp, lock)
        with self.assertRaisesRegex(hub.HubError, "demo, zwei"):
            self._call(hub.sync)

    def test_sync_force_backs_up_then_restores(self) -> None:
        out, _ = self._call(hub.sync, force=True)
        self.assertEqual(self._backup().read_bytes(), self.edited)
        self.assertEqual(self.stored.read_bytes(), hub.canonical(package()))
        self.assertIn("gesichert", out[0])

    def test_add_refuses_then_force_backs_up(self) -> None:
        with self.assertRaisesRegex(hub.HubError, "lokal verändert"):
            self._call(hub.add, "demo")
        self.assertEqual(self.stored.read_bytes(), self.edited)
        self._call(hub.add, "demo", force=True)
        self.assertEqual(self._backup().read_bytes(), self.edited)
        self.assertEqual(self.stored.read_bytes(), hub.canonical(package()))

    def test_remove_refuses_then_force_backs_up(self) -> None:
        with self.assertRaisesRegex(hub.HubError, "lokal verändert"):
            hub.remove(self.tmp, "demo")
        self.assertEqual(self.stored.read_bytes(), self.edited)
        self.assertIn("demo", hub.read_lock(self.tmp))
        hub.remove(self.tmp, "demo", force=True)
        self.assertEqual(self._backup().read_bytes(), self.edited)
        self.assertFalse(self.stored.exists())

    def test_unmodified_store_needs_no_force(self) -> None:
        self.stored.write_bytes(hub.canonical(package()))
        out, requested = self._call(hub.sync)
        self.assertEqual((out, requested), (["demo 1.0.0: aktuell"], []))
        self.assertFalse((self.tmp / hub.BACKUP).exists())


class LocalPackageTest(TempCase):
    """Eigene Pakete unter .ruttla/packages/ laufen im Scan und überleben add/sync/remove."""

    def setUp(self) -> None:
        super().setUp()
        (self.tmp / "run.sh").write_text("echo TODO-HUB\n", encoding="utf-8")
        self.src = write_source(self.tmp / hub.LOCAL_PACKAGES, named("eigen"))

    def _scan(self, engine: Path) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, PYTHONPATH=str(SRC), RUTTLA_ENGINE_BIN=str(engine))
        return subprocess.run([sys.executable, "-m", "ruttla", str(self.tmp), "--check", "hub.*",
                               "--format", "json"], env=env, text=True, encoding="utf-8",
                              capture_output=True, timeout=300)

    def test_local_rule_runs_in_scan(self) -> None:
        proc = self._scan(require_engine(self))
        self.assertEqual(proc.returncode, EXIT_OK, proc.stdout[-2000:] + proc.stderr[-2000:])
        result = {r["check_id"]: r for r in json.loads(proc.stdout)["results"]}["hub.eigen.todo_marker"]
        self.assertEqual(result["status"], "fail")

    def test_broken_local_package_aborts_scan(self) -> None:
        engine = require_engine(self)
        (self.src / "package.toml").write_text('name = "eigen"\n', encoding="utf-8")
        proc = self._scan(engine)
        self.assertEqual(proc.returncode, EXIT_CRASH, proc.stdout[-2000:])
        self.assertIn("eigen", proc.stdout + proc.stderr)

    def test_same_name_installed_and_local_aborts(self) -> None:
        raw = hub.canonical(named("eigen"))
        hub.write_lock(self.tmp, {"eigen": {"version": "1.0.0", "sha256": hub.sha256(raw)}})
        with self.assertRaisesRegex(hub.HubError, "installiert und unter"):
            hub.register_locked(self.tmp)

    def test_hub_commands_leave_local_packages_alone(self) -> None:
        before = {p: p.read_bytes() for p in self.src.rglob("*") if p.is_file()}
        ensure_checks_loaded()
        with mock.patch.object(hub, "_fetch", FakeHub(package())), \
                mock.patch.object(hub, "verify_signature", lambda raw, bundle: None):
            hub.add(self.tmp, "demo")
            hub.sync(self.tmp, force=True)
            hub.remove(self.tmp, "demo", force=True)
        self.assertEqual({p: p.read_bytes() for p in self.src.rglob("*") if p.is_file()}, before)

    def test_symlink_in_package_rejected(self) -> None:
        secret = self.tmp / "geheim.toml"
        secret.write_text("x = 1\n", encoding="utf-8")
        (self.src / "rules" / "universal" / "hub.eigen.leck.toml").symlink_to(secret)
        with self.assertRaisesRegex(hub.HubError, "symbolischer Link"):
            hub.read_source(self.src)


OWNER = hub.HUB_REPO.split("/")[0]


class SubmitTest(TempCase):
    """Einreichen nur mit --yes, nur nach bestandener Prüfung, nie als Versionsänderung."""

    def setUp(self) -> None:
        super().setUp()
        ensure_checks_loaded()
        self.engine = require_engine(self)
        self.calls: list[list[str]] = []
        self.copied: list[str] = []

    def _submit(self, pkg: dict, *, yes: bool, login: str = OWNER) -> list[str]:
        write_source(self.tmp / hub.LOCAL_PACKAGES, pkg)

        def sh(cmd: list[str], cwd: Path | None = None) -> str:
            self.calls.append(cmd)
            if cmd[:3] == ["gh", "repo", "clone"]:
                (Path(cmd[4]) / "packages").mkdir(parents=True)
            if cmd[:2] == ["git", "add"]:
                dest = Path(cwd) / "packages" / pkg["name"]
                self.copied = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
            return {"api": login, "pr": "https://github.com/x/pull/1"}.get(cmd[1], "")

        env = mock.patch.dict(os.environ, {"RUTTLA_ENGINE_BIN": str(self.engine)})
        with env, mock.patch.object(hub, "_fetch", FakeHub(package())), mock.patch.object(hub, "_sh", sh):
            return hub.submit(self.tmp, pkg["name"], yes)

    def test_without_yes_nothing_is_sent(self) -> None:
        out = self._submit(package(version="1.1.0"), yes=False)
        self.assertEqual(self.calls, [])
        self.assertIn("Nichts gesendet", out[-1])

    def test_owner_pushes_branch_and_opens_pr(self) -> None:
        out = self._submit(package(version="1.1.0"), yes=True)
        self.assertNotIn(["gh", "repo", "fork", "--remote", "--remote-name", "fork"], self.calls)
        self.assertIn(["git", "push", "-u", "origin", "paket/demo-1.1.0"], self.calls)
        pr = next(c for c in self.calls if c[:3] == ["gh", "pr", "create"])
        self.assertIn(f"{OWNER}:paket/demo-1.1.0", pr)
        self.assertEqual(self.copied, ["package.toml", "rules/universal/hub.demo.todo_marker.toml"])
        self.assertTrue(any("PR angelegt" in line for line in out))

    def test_contributor_goes_through_fork(self) -> None:
        self._submit(named("fremd"), yes=True, login="jemand")
        self.assertIn(["gh", "repo", "fork", "--remote", "--remote-name", "fork"], self.calls)
        self.assertIn(["git", "push", "-u", "fork", "paket/fremd-1.0.0"], self.calls)

    def test_changed_content_under_published_version_rejected(self) -> None:
        with self.assertRaisesRegex(hub.HubError, "Version erhöhen"):
            self._submit(package(description="anders"), yes=True)
        self.assertEqual(self.calls, [])

    def test_identical_to_published_is_a_no_op(self) -> None:
        out = self._submit(package(), yes=True)
        self.assertIn("nichts einzureichen", out[0])
        self.assertEqual(self.calls, [])

    def test_failing_admission_sends_nothing(self) -> None:
        pkg = package(version="1.1.0")
        pkg["rules"] = {"universal/hub.demo.todo_marker.toml": RULE.replace('expect = "pass"', 'expect = "fail"')}
        with self.assertRaisesRegex(hub.HubError, "Aufnahmeprüfung"):
            self._submit(pkg, yes=True)
        self.assertEqual(self.calls, [])
