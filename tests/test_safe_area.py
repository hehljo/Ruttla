"""Healthy controls precede isolated defects; no device/runtime assertion."""
import unittest

from _support import cli_json, make_tree
from ruttla.config import Config
from ruttla.core import Context, Status
from ruttla.checks.web.safe_area import EDGES, HEALTHY, ID, check_safe_area


def inspect(css):
    with make_tree({"src/layout.css": css}) as root:
        return check_safe_area(Context(root, Config()))


class SafeAreaTests(unittest.TestCase):
    def test_01_healthy_before_each_isolated_edge_defect(self):
        for edge in EDGES:
            healthy = f".bar {{ margin-{edge}: env(safe-area-inset-{edge}, 0px); padding-{edge}: 6px; }}"
            with self.subTest(edge=edge):
                self.assertEqual(inspect(healthy).status, Status.PASS)
                broken = healthy.replace(f"padding-{edge}: 6px", f"padding-{edge}: env(safe-area-inset-{edge}, 0px)")
                result = inspect(broken)
                self.assertEqual(result.status, Status.FAIL)
                self.assertEqual(len(result.findings), 1)
                self.assertIn(edge, result.findings[0].message)

    def test_02_observed_shorthand_defect_and_nested_media(self):
        self.assertEqual(inspect(HEALTHY).status, Status.PASS)
        broken = HEALTHY.replace("padding-bottom: 6px", "padding-bottom: calc(4px + env(safe-area-inset-bottom, 0px))")
        for css in [broken, "@media (min-width: 640px) {\n" + broken + "\n}"]:
            with self.subTest(css=css):
                result = inspect(css)
                self.assertEqual((result.status, result.units_examined), (Status.FAIL, 1))

    def test_03_shorthand_expansion_and_precedence(self):
        cases = [
            ("margin: env(safe-area-inset-bottom)", "padding-bottom: env(safe-area-inset-bottom)"),
            ("margin: env(safe-area-inset-bottom) 0", "padding: 0 0 env(safe-area-inset-bottom)"),
            ("margin: 0 0 env(safe-area-inset-bottom) 0", "padding: env(safe-area-inset-bottom)"),
        ]
        for margin, padding in cases:
            with self.subTest(margin=margin):
                self.assertEqual(inspect(f".bar {{ {margin}; padding: 6px; }}").status, Status.PASS)
                self.assertEqual(inspect(f".bar {{ {margin}; {padding}; }}").status, Status.FAIL)
        for tail, expected in [
            ("padding: 6px", Status.FAIL),
            ("padding-bottom: 6px !important", Status.PASS),
            ("padding-bottom: 6px", Status.FAIL),
        ]:
            css = ".bar { margin-bottom: env(safe-area-inset-bottom); padding-bottom: env(safe-area-inset-bottom) !important; " + tail + "; }"
            with self.subTest(tail=tail):
                # Non-important shorthand cannot override important longhand.
                self.assertEqual(inspect(css).status, expected)

    def test_04_lexical_cross_box_and_same_side_controls(self):
        for css in [
            HEALTHY + "/* .bad { margin-bottom: env(safe-area-inset-bottom); padding-bottom: env(safe-area-inset-bottom); } */",
            HEALTHY + '''.note::after { content: "margin-bottom: env(safe-area-inset-bottom); padding-bottom: env(safe-area-inset-bottom);"; }''',
            ".a { margin-bottom: env(safe-area-inset-bottom); } .b { padding-bottom: env(safe-area-inset-bottom); }",
            ".bar { margin-top: env(safe-area-inset-top); padding-bottom: env(safe-area-inset-bottom); }",
            HEALTHY.replace("padding-bottom: 6px", "padding-bottom: env(safe-area-inset-bottom); padding: 6px"),
        ]:
            with self.subTest(css=css):
                self.assertEqual(inspect(css).status, Status.PASS)

    def test_05_unknown_subjects_never_pass(self):
        for css in [".bar { padding: 6px; }", ".bar { margin: var(--safe-area-inset-bottom); }",
                    ".bar { margin-bottom: calc(env(safe-area-inset-bottom) - 10px); }",
                    HEALTHY + " .bar { padding-inline: var(--spacing); }"]:
            result = inspect(css)
            # Independent locally measured blocks may still pass; unresolved-only may not.
            self.assertEqual(result.status, Status.PASS if css.startswith(HEALTHY) else Status.UNMEASURED)
        self.assertEqual(inspect(HEALTHY.replace("padding-bottom: 6px", "padding-block: env(safe-area-inset-bottom)")).status, Status.UNMEASURED)

    def test_06_cli_advisory_strict_policy_and_location(self):
        with make_tree({"src/layout.css": HEALTHY}) as root:
            code, report = cli_json(root, "--check", ID)
            self.assertEqual((code, report["results"][0]["status"]), (0, "pass"))
        broken = ".bar {\n  margin-bottom: env(safe-area-inset-bottom);\n  padding-bottom: env(safe-area-inset-bottom);\n}"
        with make_tree({"src/layout.css": broken}) as root:
            code, report = cli_json(root, "--check", ID)
            self.assertEqual((code, report["results"][0]["status"]), (0, "fail"))
            finding = report["results"][0]["findings"][0]
            self.assertFalse(finding["blocking"])
            self.assertEqual((finding["file"], finding["line"]), ("src/layout.css", 3))
            strict, _ = cli_json(root, "--check", ID, "--strict")
            self.assertEqual(strict, 1)


if __name__ == "__main__":
    unittest.main()
