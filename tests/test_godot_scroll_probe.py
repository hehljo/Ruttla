"""Scroll coverage presence: healthy first, then isolated missing-call defects."""
from __future__ import annotations

import unittest

from _support import cli_json, make_tree
from ruttla.checks.godot.scroll_probe import CALL, ID, PROJECT, SCENE


class ScrollProbeTests(unittest.TestCase):
    def scan(self, extra=None, *, scene=SCENE, args=()):
        files = {"project.godot": PROJECT, "menu.tscn": scene}
        files.update(extra or {})
        with make_tree(files) as tmp:
            code, report = cli_json(tmp, "--check", ID, *args)
        self.assertNotIn("error", report)
        self.assertEqual(len(report["results"]), 1)
        return code, report["results"][0]

    def test_healthy_then_individual_missing_call_mutations(self):
        code, result = self.scan({"tests/swipe.gd": CALL})
        self.assertEqual((code, result["status"], result["units_examined"]), (0, "pass", 1))
        for body in ("", CALL.replace("drag_scrolls", "ensure_control_visible"),
                     '# ' + CALL.replace("\n", " "),
                     'var example = "RuttlaScrollProbe.drag_scrolls(s, p)"\n',
                     'var example = """\nawait drag_scrolls(s, p)\n"""\n',
                     "static func drag_scrolls(s, p):\n\tpass\n"):
            with self.subTest(body=body):
                code, result = self.scan({"tests/swipe.gd": body})
                self.assertEqual((code, result["status"], result["units_examined"]), (0, "fail", 1))
                self.assertEqual(len(result["findings"]), 1)
                finding = result["findings"][0]
                self.assertEqual((finding["file"], finding["line"]), ("menu.tscn", 3))
                self.assertEqual(finding["severity"], "warning")
                self.assertFalse(finding["blocking"])
        code, _ = self.scan(args=("--strict",))
        self.assertEqual(code, 1)  # Explicit strict policy still applies to advisories.

    def test_reach_and_multiline_calls_in_scripts(self):
        for body in (CALL.replace("drag_scrolls", "reach_by_drag"),
                     "func check():\n\tawait probe.drag_scrolls\n\t\t(scroll, origin)\n"):
            with self.subTest(body=body):
                code, result = self.scan({"checks/swipe.gd": body})
                self.assertEqual((code, result["status"]), (0, "pass"))

    def test_empty_subject_is_unmeasured(self):
        for scene in ("", SCENE.replace('type="ScrollContainer"', 'type="VBoxContainer"'),
                      SCENE.replace('type="Button"', 'type="Label"'),
                      SCENE.replace('parent="List/Rows"', 'parent="."')):
            with self.subTest(scene=scene):
                code, result = self.scan({"tests/swipe.gd": CALL}, scene=scene)
                self.assertEqual((code, result["status"], result["units_examined"]),
                                 (2, "unmeasured", 0))
        with make_tree({"menu.tscn": SCENE}) as tmp:
            code, report = cli_json(tmp, "--check", ID)
        self.assertEqual((code, report["results"][0]["status"]), (2, "unmeasured"))

    def test_dynamic_cross_file_and_custom_inheritance(self):
        files = {
            "menu.gd": "var list = ScrollContainer.new()\n",
            "base.gd": "class_name CardBase\nextends PanelContainer\n",
            "card.gd": "class_name BuyCard\nextends CardBase\n",
            "builder.gd": "var card = BuyCard.new()\n",
            "tests/swipe.gd": CALL,
        }
        code, result = self.scan(files, scene="")
        self.assertEqual((code, result["status"], result["units_examined"]), (0, "pass", 1))
        files["tests/swipe.gd"] = CALL.replace("drag_scrolls", "ensure_control_visible")
        code, result = self.scan(files, scene="")
        self.assertEqual((code, result["status"], result["units_examined"]), (0, "fail", 1))
        self.assertEqual(result["findings"][0]["file"], "menu.gd")
        self.assertEqual(result["findings"][0]["line"], 1)

    def test_scene_dynamic_content_and_candidate_counts(self):
        scene = SCENE.replace('type="Button"', 'type="Label"')
        scene += '[node name="Other" type="ScrollContainer" parent="."]\n'
        extra = {"builder.gd": "var b = Button.new()\n", "tests/swipe.gd": CALL}
        code, result = self.scan(extra, scene=scene)
        self.assertEqual((code, result["status"], result["units_examined"]), (0, "pass", 2))
        extra["tests/swipe.gd"] = ""
        _, result = self.scan(extra, scene=scene)
        self.assertEqual(result["units_examined"], 2)
        self.assertEqual(len(result["findings"]), 2)

    def test_installed_probe_alone_is_not_application_call(self):
        probe = ("class_name RuttlaScrollProbe\nextends RefCounted\n"
                 "static func drag_scrolls(s, p):\n\tpass\n"
                 "static func reach_by_drag(s, p):\n\tawait drag_scrolls(s, p)\n")
        extra = {"tests/support/scroll_probe.gd": probe, "tests/swipe.gd": CALL}
        _, result = self.scan(extra)
        self.assertEqual(result["status"], "pass")
        extra["tests/swipe.gd"] = ""
        _, result = self.scan(extra)
        self.assertEqual(result["status"], "fail")
        extra = {"addons/ruttla_probes/result.gd": "extends RefCounted\n"}
        _, result = self.scan(extra)
        self.assertEqual(result["status"], "fail")

    def test_nearest_project_isolation(self):
        files = {
            "project.godot": PROJECT, "menu.tscn": SCENE, "tests/swipe.gd": CALL,
            "nested/project.godot": PROJECT, "nested/menu.tscn": SCENE,
        }
        with make_tree(files) as tmp:
            code, report = cli_json(tmp, "--check", ID)
        result = report["results"][0]
        self.assertEqual((code, result["status"], result["units_examined"]), (0, "fail", 2))
        self.assertEqual([f["file"] for f in result["findings"]], ["nested/menu.tscn"])
        files["nested/tests/swipe.gd"] = CALL
        files["tests/swipe.gd"] = ""
        with make_tree(files) as tmp:
            _, report = cli_json(tmp, "--check", ID)
        self.assertEqual([f["file"] for f in report["results"][0]["findings"]], ["menu.tscn"])

    def test_inventory_exclusion_and_no_fake_constructor(self):
        files = {"tests/swipe.gd": CALL,
                 ".ruttla.toml": '[gate]\nexclude = ["tests/*"]\n'}
        _, result = self.scan(files)
        self.assertEqual(result["status"], "fail")
        for body in ('# var s = ScrollContainer.new()\nvar b = Button.new()\n',
                     'var s = "ScrollContainer.new()"\nvar b = Button.new()\n',
                     'var s = ScrollContainer.new()\nvar b = "Button.new()"\n'):
            with self.subTest(body=body):
                code, result = self.scan({"menu.gd": body}, scene="")
                self.assertEqual((code, result["status"]), (2, "unmeasured"))

    def test_scene_root_scroll_and_sibling_prefix(self):
        scene = ('[gd_scene format=3]\n[node name="List" type="ScrollContainer"]\n'
                 '[node name="Buy" type="TextureButton" parent="."]\n')
        _, result = self.scan({"test.gd": CALL}, scene=scene)
        self.assertEqual((result["status"], result["units_examined"]), ("pass", 1))
        scene = SCENE.replace('parent="List/Rows"', 'parent="ListOther"')
        _, result = self.scan(scene=scene)
        self.assertEqual(result["status"], "unmeasured")


if __name__ == "__main__":
    unittest.main()
