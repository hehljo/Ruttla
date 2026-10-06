"""A healthy configured catalog precedes each isolated missing-key defect."""
import unittest
from _support import cli_json, make_tree

RULE = 'i18n.catalog_key_parity'
PROJECT = '[internationalization]\nlocale/translations=PackedStringArray("res://localization/ui.de.translation", "res://localization/ui.en.translation")\n'
CATALOG = 'keys,de,en\nUI_PLAY,Spielen,Play\nTALENT_HP_DESC,Leben,Health\n'


class GodotTranslationTests(unittest.TestCase):
    def scan(self, files):
        with make_tree(files) as tmp:
            return cli_json(tmp, '--check', RULE, '--strict')

    def test_healthy_before_each_independent_defect(self):
        healthy = {'project.godot': PROJECT, 'localization/ui.csv': CATALOG,
                   'menu.gd': 'var label = tr("UI_PLAY")\nvar talent = {"desc_key": "TALENT_HP_DESC"}\n',
                   'menu.tscn': '[node name="Hint" type="Label"]\ntext = "UI_PLAY"\n'}
        for file, old, new in [
            ('menu.gd', 'tr("UI_PLAY")', 'tr("UI_MISSING")'),
            ('menu.gd', '"TALENT_HP_DESC"', '"TALENT_HP_MISSING_DESC"'),
            ('menu.tscn', '"UI_PLAY"', '"UI_MISSING"'),
            ('localization/ui.csv', 'UI_PLAY,Spielen,Play', 'UI_PLAY,Spielen,'),
        ]:
            with self.subTest(file=file, new=new):
                code, report = self.scan(healthy)
                self.assertEqual(code, 0)
                self.assertEqual(report['results'][0]['status'], 'pass')
                defective = dict(healthy)
                defective[file] = defective[file].replace(old, new)
                code, report = self.scan(defective)
                self.assertEqual(code, 1)
                self.assertEqual(report['results'][0]['status'], 'fail')
                self.assertTrue(report['results'][0]['findings'])

    def test_nested_projects_cannot_supply_each_others_keys(self):
        files = {'A/project.godot': PROJECT, 'A/localization/ui.csv': CATALOG,
                 'A/main.gd': 'var text = tr("UI_PLAY")\n',
                 'B/project.godot': PROJECT, 'B/localization/ui.csv': 'keys,de,en\nUI_OTHER,Andere,Other\n',
                 'B/main.gd': 'var text = tr("UI_OTHER")\n'}
        code, _ = self.scan(files)
        self.assertEqual(code, 0)
        files['B/main.gd'] = 'var text = tr("UI_PLAY")\n'
        code, report = self.scan(files)
        self.assertEqual(code, 1)
        self.assertEqual(report['results'][0]['findings'][0]['file'], 'B/main.gd')

    def test_missing_configuration_and_dynamic_references_are_unmeasured(self):
        for settings, source in [(' [application]\n', 'tr("UI_PLAY")'),
                                 (PROJECT, 'tr(definition.desc_key)')]:
            code, report = self.scan({'project.godot': settings,
                                     'localization/ui.csv': CATALOG,
                                     'menu.gd': source})
            # Catalog parity is measured; no dynamic/provider completeness claim.
            self.assertEqual(report['results'][0]['status'], 'pass')
            self.assertEqual(code, 0)


if __name__ == '__main__':
    unittest.main()
