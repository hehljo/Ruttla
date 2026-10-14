"""Real test-only schemes and technical literals, then isolated UI defects."""
import unittest

from _support import cli_json, make_tree
from ruttla.checks.apple._release_common import _HEALTHY_PROJECT


class NativeTestScopes(unittest.TestCase):
    def brand(self, source, extension="swift"):
        with make_tree({"package.json": '{"name":"acme-web"}',
                        "P.xcodeproj/project.pbxproj": 'INFOPLIST_KEY_CFBundleDisplayName = Acme;',
                        "probe." + extension: source}) as root:
            return cli_json(root, "--check", "brand.hardcoded_in_display", "--strict")

    def test_technical_literals_then_visible_counterparts(self):
        for source, ext in [
            ('root.appendingPathComponent("Acme-Probe")', "swift"),
            ('root.appendingPathComponent("Acme-Test-\\(UUID().uuidString)")', "swift"),
            ('name = "Acme-Test-" + family', "py"),
            ('run(callback, "acme_storage_key")', "mjs"),
        ]:
            with self.subTest(source=source):
                code, report = self.brand(source, ext)
                self.assertEqual(code, 0, report)
        for source, ext in [
            ('Text("Acme-Probe")', "swift"),
            ('Text("Acme-Test-\\(UUID().uuidString)")', "swift"),
            ('Text(\n "Acme-Probe"\n)', "swift"),
            ('root.appendingPathComponent("Acme-Probe"); Text("Acme-Probe")', "swift"),
            ('const view = <h1>Acme-Probe</h1>', "tsx"),
            ('const view = <h1>{"Acme-Probe"}</h1>', "tsx"),
            ('label.textContent = "Acme-Probe"', "js"),
            ('Label(text="Acme-Probe")', "py"),
        ]:
            with self.subTest(source=source):
                code, report = self.brand(source, ext)
                self.assertEqual(code, 1, report)
                check = next(check for check in report["results"] if check["check_id"] == "brand.hardcoded_in_display")
                self.assertEqual(len(check["findings"]), 1, report)

    def scheme(self, project, attributes='buildForTesting="YES" buildForArchiving="NO"', target="AAA111"):
        scheme = ('<Scheme><BuildAction><BuildActionEntries><BuildActionEntry ' + attributes
            + '><BuildableReference BlueprintIdentifier="' + target
            + '" ReferencedContainer="container:P.xcodeproj"/></BuildActionEntry>'
            '</BuildActionEntries></BuildAction><TestAction/></Scheme>')
        with make_tree({"P.xcodeproj/project.pbxproj": project,
                        "P.xcodeproj/xcshareddata/xcschemes/Probe.xcscheme": scheme}) as root:
            return cli_json(root, "--check", "apple.release.archive_action", "--strict")

    def test_test_only_scheme_then_independent_defects(self):
        project = _HEALTHY_PROJECT.replace('name = App;',
            'name = App; productType = "com.apple.product-type.bundle.unit-test";')
        code, report = self.scheme(project)
        self.assertEqual(code, 0, report)
        for changed, attributes, target in [
            (project.replace("bundle.unit-test", "application"), 'buildForTesting="YES" buildForArchiving="NO"', "AAA111"),
            (project, 'buildForTesting="YES" buildForArchiving="YES"', "AAA111"),
            (project, 'buildForTesting="NO" buildForArchiving="NO"', "AAA111"),
            (project, 'buildForTesting="YES" buildForArchiving="NO"', "MISSING"),
        ]:
            code, report = self.scheme(changed, attributes, target)
            self.assertEqual(code, 1, report)

    def test_python_bootstrap_then_actual_ui_concatenation(self):
        for source, expected in [
            ('bootstrap = "root.mkdir(parents=True); " + suffix', 0),
            ('bootstrap = "root.mkdir(parents=True); " + suffix; text = "Bitte warten " + name', 1),
            ('text = "Hallo; " + name', 1),
        ]:
            with make_tree({"probe.py": source}) as root:
                code, report = cli_json(root, "--check", "i18n.string_concatenation", "--strict")
                self.assertEqual(code, expected, report)

    def test_unsigned_test_project_then_app_or_signing_mutation(self):
        project = '''TargetAttributes = {};
objects = {
 T = { isa = PBXNativeTarget; productType = "com.apple.product-type.bundle.unit-test"; };
 C1 = { isa = XCBuildConfiguration; buildSettings = { CODE_SIGNING_ALLOWED = NO; }; };
 C2 = { isa = XCBuildConfiguration; buildSettings = { CODE_SIGNING_ALLOWED = NO; }; };
};'''
        for source, expected in [(project, 0),
                (project.replace("bundle.unit-test", "application"), 1),
                (project.replace("CODE_SIGNING_ALLOWED = NO;", "", 1), 1)]:
            with make_tree({"P.xcodeproj/project.pbxproj": source}) as root:
                code, report = cli_json(root, "--check", "apple.project_settings", "--strict")
                self.assertEqual(code, expected, report)


if __name__ == "__main__":
    unittest.main()
