"""Charakterisierung der Plattform-Erkennung (P10-T002/T003).

Jeder Fall hält ein einzelnes Erkennungssignal fest — vor dem Umbau auf das
Erkennungsmanifest geschrieben, damit der Umbau ein Erfolgskriterium hat.
"""

from __future__ import annotations

import copy
import tomllib
import unittest
from importlib import resources

from _support import ensure_checks_loaded, make_tree

# Vor dem Import einzelner Pack-Module laden: deren Import füllt REGISTRY
# teilweise, und ensure_checks_loaded() hielte die Registry dann für komplett.
ensure_checks_loaded()

from ruttla.checks.unreal._common import _is_unreal  # noqa: E402
from ruttla.config import Config  # noqa: E402
from ruttla.context import Context  # noqa: E402
from ruttla.platforms import (  # noqa: E402
    MANIFEST, ManifestError, detect_platforms, parse_manifest, platform_present,
)

# (Name, Dateibaum, erwartete Plattformen ohne "universal")
CASES: list[tuple[str, dict[str, str], set[str]]] = [
    ("leer", {"README.md": "# x\n"}, set()),
    ("swift", {"App/main.swift": "print(1)\n"}, {"apple"}),
    ("xcodeproj-ordner", {"App.xcodeproj/project.pbxproj": "// x\n"}, {"apple"}),
    ("ts", {"src/a.ts": "export const a = 1\n"}, {"web"}),
    ("tsx", {"src/a.tsx": "export const a = 1\n"}, {"web"}),
    ("jsx", {"src/a.jsx": "export const a = 1\n"}, {"web"}),
    ("package.json", {"package.json": "{}\n"}, {"web"}),
    ("js allein ist kein web", {"src/a.js": "var a = 1\n"}, set()),
    ("gd", {"player.gd": "extends Node\n"}, {"godot"}),
    ("project.godot", {"project.godot": "config_version=5\n"}, {"godot"}),
    ("cs", {"A.cs": "class A {}\n"}, {"dotnet"}),
    ("csproj", {"A.csproj": "<Project/>\n"}, {"dotnet"}),
    ("xaml", {"Main.xaml": "<Window/>\n"}, {"dotnet"}),
    ("uproject", {"Game.uproject": "{}\n"}, {"unreal"}),
    ("uplugin", {"P.uplugin": "{}\n"}, {"unreal"}),
    ("build.cs", {"Source/Game/Game.Build.cs": "class X {}\n"}, {"unreal", "dotnet"}),
    ("target.cs", {"Source/Game.Target.cs": "class X {}\n"}, {"unreal", "dotnet"}),
    ("uclass in cpp", {"A.cpp": "UCLASS()\nclass A {};\n"}, {"unreal"}),
    ("uenum in h", {"A.h": "UENUM(BlueprintType)\nenum class E {};\n"}, {"unreal"}),
    ("cpp ohne ue-makro", {"A.cpp": "int main() { return 0; }\n"}, set()),
    ("py", {"a.py": "x = 1\n"}, {"python"}),
    ("gpiozero", {"a.py": "import gpiozero\n"}, {"python", "raspberry"}),
    ("from rpi.gpio", {"a.py": "from RPi.GPIO import setup\n"}, {"python", "raspberry"}),
    ("serial", {"a.py": "  import serial\n"}, {"python", "raspberry"}),
    ("boardgame ist keine hardware", {"a.py": "import boardgame\n"}, {"python"}),
    ("auskommentiert", {"a.py": "# import gpiozero\n"}, {"python"}),
]


def _ctx(tmp: str) -> Context:
    return Context(tmp, Config())


class PlatformDetectionCharacterization(unittest.TestCase):

    def test_each_single_signal(self) -> None:
        for name, tree, expected in CASES:
            with self.subTest(name), make_tree(tree) as tmp:
                got = detect_platforms(_ctx(tmp)) - {"universal"}
                self.assertEqual(got, expected)

    def test_universal_is_always_present(self) -> None:
        with make_tree({"README.md": "# x\n"}) as tmp:
            self.assertIn("universal", detect_platforms(_ctx(tmp)))

    def test_excluded_glob_does_not_switch_platform_on(self) -> None:
        tree = {"fixtures/App.xcodeproj/project.pbxproj": "// x\n",
                ".ruttla.toml": '[gate]\nexclude = ["fixtures/*"]\n'}
        with make_tree(tree) as tmp:
            cfg = Config.load(tmp, None)
            self.assertNotIn("apple", detect_platforms(Context(tmp, cfg)))

    def test_unreal_pack_gate_agrees_with_detection(self) -> None:
        # Zwei Listen derselben Menge driften: die Pack-Prüfung muss für jedes
        # Unreal-Signal genauso entscheiden wie die Plattform-Erkennung.
        for name, tree, expected in CASES:
            with self.subTest(name), make_tree(tree) as tmp:
                ctx = _ctx(tmp)
                self.assertEqual(_is_unreal(ctx), "unreal" in detect_platforms(ctx))


def _raw_manifest() -> dict:
    text = resources.files("ruttla").joinpath("platforms.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def _single_signal_trees(name: str) -> list[tuple[str, dict[str, str]]]:
    """Ein Dateibaum je Signal, direkt aus dem Manifest abgeleitet — der Test
    pflegt keine eigene Liste, sondern misst jede Zeile des Manifests."""
    spec = MANIFEST[name]
    out: list[tuple[str, dict[str, str]]] = []
    for ext in sorted(spec.extensions):
        out.append((f"ext {ext}", {f"sub/x{ext}": "x\n"}))
    for fname in sorted(spec.file_names):
        out.append((f"name {fname}", {f"sub/{fname}": "x\n"}))
    for suffix in spec.file_suffixes:
        out.append((f"suffix {suffix}", {f"sub/Game.{suffix}": "x\n"}))
    for suffix in spec.dir_suffixes:
        out.append((f"dir {suffix}", {f"sub/App{suffix}/inner.txt": "x\n"}))
    for marker in spec.root_markers:
        path = "/".join(seg.replace("*", "X") for seg in marker)
        out.append((f"marker {'/'.join(marker)}", {f"sub/{path}": "x\n"}))
    for i, signal in enumerate(spec.content):
        out.append((f"content {i}", {f"sub/x{signal.extensions[0]}": _first_example(name, i)}))
    return out


def _first_example(name: str, index: int) -> str:
    return _raw_manifest()["platforms"][name]["content"][index]["examples"][0] + "\n"


class ManifestSignals(unittest.TestCase):

    def test_every_manifest_signal_switches_its_platform_on(self) -> None:
        for name, spec in MANIFEST.items():
            if spec.always:
                continue
            trees = _single_signal_trees(name)
            self.assertTrue(trees, f"{name}: kein Signal abgeleitet")
            for label, tree in trees:
                # requires: die Vorbedingung im selben Baum mit herstellen
                for dep in spec.requires:
                    _, dep_tree = _single_signal_trees(dep)[0]
                    tree = {**dep_tree, **tree}
                with self.subTest(platform=name, signal=label), make_tree(tree) as tmp:
                    ctx = _ctx(tmp)
                    self.assertIn(name, detect_platforms(ctx))
                    self.assertTrue(platform_present(ctx, name))

    def test_unreal_pack_gate_follows_every_unreal_signal(self) -> None:
        for label, tree in _single_signal_trees("unreal"):
            with self.subTest(label), make_tree(tree) as tmp:
                self.assertTrue(_is_unreal(_ctx(tmp)))

    def test_raspberry_pack_uses_the_manifest_pattern(self) -> None:
        from ruttla.checks.raspberry import rules
        from ruttla.platforms import content_patterns
        self.assertIs(rules.HW_IMPORT, content_patterns("raspberry")[0])

    def test_content_signal_ignores_rule_definition_files(self) -> None:
        # Eine Testdatei, die das Merkmal nur beschreibt, schaltet nichts ein.
        tree = {"test_hw.py": "def test_x():\n    pass\nimport gpiozero\n"}
        with make_tree(tree) as tmp:
            self.assertNotIn("raspberry", detect_platforms(_ctx(tmp)))


class ManifestValidation(unittest.TestCase):
    """Jede Verletzung einzeln: ein ungültiges Manifest bricht ab, nie still."""

    def _broken(self, mutate) -> None:
        data = copy.deepcopy(_raw_manifest())
        mutate(data)
        with self.assertRaises(ManifestError):
            parse_manifest(data)

    def test_shipped_manifest_is_valid(self) -> None:
        self.assertEqual(set(parse_manifest(_raw_manifest())), set(MANIFEST))

    def test_unknown_platform_key(self) -> None:
        self._broken(lambda d: d["platforms"]["apple"].update(extension=[".swift"]))

    def test_unknown_top_level_key(self) -> None:
        self._broken(lambda d: d.update(platform={}))

    def test_wrong_version(self) -> None:
        self._broken(lambda d: d.update(manifest_version=2))

    def test_zero_platforms(self) -> None:
        self._broken(lambda d: d.update(platforms={}))

    def test_platform_without_signal(self) -> None:
        self._broken(lambda d: d["platforms"].update(ghost={"pack": False}))

    def test_unknown_requires(self) -> None:
        self._broken(lambda d: d["platforms"]["raspberry"].update(requires=["cobol"]))

    def test_missing_pack_flag(self) -> None:
        self._broken(lambda d: d["platforms"]["web"].pop("pack"))

    def test_example_that_does_not_match(self) -> None:
        self._broken(lambda d: d["platforms"]["raspberry"]["content"][0]["examples"]
                     .append("import numpy"))

    def test_counter_example_that_matches(self) -> None:
        self._broken(lambda d: d["platforms"]["unreal"]["content"][0]["counter_examples"]
                     .append("UCLASS()"))

    def test_content_without_counter_examples(self) -> None:
        self._broken(lambda d: d["platforms"]["unreal"]["content"][0].pop("counter_examples"))

    def test_invalid_regex(self) -> None:
        self._broken(lambda d: d["platforms"]["unreal"]["content"][0].update(pattern="("))

    def test_manifest_ships_inside_the_package(self) -> None:
        # resources.files liest aus dem installierten Paket, nicht aus dem Repo.
        self.assertTrue(resources.files("ruttla").joinpath("platforms.toml").is_file())


ASYNC_VOID = "class A { private async void Load(string path) { await Task.Delay(1); } }\n"
UNITY = "U/ProjectSettings/ProjectVersion.txt"


def _findings(tmp: str, check_id: str) -> list[str]:
    from ruttla.engine import run_checks
    results = run_checks(_ctx(tmp), only_platform=None, only_checks=[check_id], changed=None)
    return [f.file for r in results for f in r.findings]


class ProjectRoots(unittest.TestCase):
    """P10-T003: Teilprojekte je Unterbaum, Ansprüche je Wurzel."""

    def test_unity_is_its_own_platform_not_dotnet(self) -> None:
        with make_tree({UNITY: "m_EditorVersion: 6000.0\n", "U/Assets/A.cs": ASYNC_VOID}) as tmp:
            ctx = _ctx(tmp)
            self.assertEqual(detect_platforms(ctx) - {"universal"}, {"unity"})
            self.assertEqual([r.to_dict() for r in ctx.project_roots()],
                             [{"path": "U", "platform": "unity", "marker": UNITY}])

    def test_unity_csharp_is_invisible_to_dotnet_checks(self) -> None:
        # Wirkung, nicht Existenz: derselbe Befund-Code wird im Desktop-Projekt
        # gemeldet und im Unity-Projekt nicht.
        tree = {UNITY: "x\n", "U/Assets/A.cs": ASYNC_VOID,
                "Desk/App.csproj": "<Project/>\n", "Desk/A.cs": ASYNC_VOID}
        with make_tree(tree) as tmp:
            self.assertEqual(detect_platforms(_ctx(tmp)) - {"universal"}, {"unity", "dotnet"})
            self.assertEqual(_findings(tmp, "dotnet.async_void_outside_event_handler"),
                             ["Desk/A.cs"])

    def test_universal_still_sees_claimed_files(self) -> None:
        with make_tree({UNITY: "x\n", "U/Assets/A.cs": ASYNC_VOID}) as tmp:
            ctx = _ctx(tmp)
            self.assertIn("U/Assets/A.cs", [f.rel for f in ctx.scoped("universal").files(".cs")])
            self.assertNotIn("U/Assets/A.cs", [f.rel for f in ctx.scoped("dotnet").files(".cs")])

    def test_unreal_build_rules_do_not_switch_dotnet_on(self) -> None:
        tree = {"G/Game.uproject": "{}\n", "G/Source/Game/Game.Build.cs": "class X {}\n"}
        with make_tree(tree) as tmp:
            self.assertEqual(detect_platforms(_ctx(tmp)) - {"universal"}, {"unreal"})

    def test_build_cs_without_uproject_keeps_old_behaviour(self) -> None:
        # Gegenrichtung: ohne Unreal-Wurzel gibt es keinen Anspruch.
        with make_tree({"Source/Game.Build.cs": "class X {}\n"}) as tmp:
            self.assertEqual(detect_platforms(_ctx(tmp)) - {"universal"}, {"unreal", "dotnet"})

    def test_godot_with_ios_export_yields_two_roots(self) -> None:
        tree = {"game/project.godot": "x\n", "game/player.gd": "extends Node\n",
                "game/export/ios/App.xcodeproj/project.pbxproj": "// x\n"}
        with make_tree(tree) as tmp:
            roots = [(r.path, r.platform) for r in _ctx(tmp).project_roots()]
        self.assertEqual(roots, [("game", "godot"), ("game/export/ios", "apple")])

    def test_innermost_claiming_root_wins(self) -> None:
        tree = {"G/Game.uproject": "{}\n", "G/Plugins/U/ProjectSettings/ProjectVersion.txt": "x\n",
                "G/Plugins/U/Assets/A.cs": "class A {}\n", "G/Source/Game.Build.cs": "class X {}\n"}
        with make_tree(tree) as tmp:
            claims = _ctx(tmp).claims()
        self.assertEqual(claims, {"G/Plugins/U/Assets/A.cs": "unity",
                                  "G/Source/Game.Build.cs": "unreal"})

    def test_root_at_scan_root(self) -> None:
        with make_tree({"project.godot": "x\n"}) as tmp:
            self.assertEqual([r.path for r in _ctx(tmp).project_roots()], ["."])

    def test_unity_is_reported_as_unmeasured(self) -> None:
        from _support import cli_json
        with make_tree({UNITY: "x\n", "U/Assets/A.cs": "class A {}\n"}) as tmp:
            _, report = cli_json(tmp)
        self.assertIn("unity", report["platforms_without_pack"])


if __name__ == "__main__":
    unittest.main()
