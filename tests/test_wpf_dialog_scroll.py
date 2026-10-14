"""Healthy first, then independent XML defects and explicit unknown boundaries."""
import unittest

from _support import cli_json, ensure_checks_loaded, make_tree

ensure_checks_loaded()
from ruttla.checks.dotnet.dialog_scroll import BODY, CID, SCROLL, STACK, STAR, _fixture


class DialogScrollRegression(unittest.TestCase):
    def scan(self, text):
        with make_tree({"Dialog.xaml": text}) as root:
            return cli_json(root, "--check", CID, "--strict")

    def test_healthy_then_each_defect(self):
        for body in [SCROLL, STAR]:
            code, report = self.scan(_fixture(body))
            self.assertEqual(code, 0, report)
        defects = [BODY, STACK, SCROLL.replace('="Auto"', '="Disabled"', 1),
                   BODY.replace('<Button', '<ScrollViewer Visibility="Collapsed"/><Button')]
        for body in defects:
            with self.subTest(body=body):
                code, report = self.scan(_fixture(body))
                self.assertEqual(code, 1, report)
                result = next(r for r in report["results"] if r["check_id"] == CID)
                self.assertEqual(len(result["findings"]), 1)
                self.assertEqual(result["findings"][0]["file"], "Dialog.xaml")
                self.assertGreater(result["findings"][0]["line"], 0)

    def test_unknown_is_not_green(self):
        for text in [_fixture(BODY, 'MaxHeight="{Binding Limit}"'),
                     _fixture('<custom:Form xmlns:custom="clr-namespace:Example"/>'),
                     _fixture(BODY.replace('<TextBlock', '<ListBox/><TextBlock')),
                     _fixture(BODY, ''),
                     '<Window xmlns="https://github.com/avaloniaui" SizeToContent="Height" MaxHeight="650"/>']:
            with self.subTest(text=text):
                code, report = self.scan(text)
                self.assertEqual(code, 2, report)

    def test_custom_window_root_and_comments(self):
        text = _fixture(BODY).replace('<Window ', '<base:ScaledWindow xmlns:base="clr-namespace:Example" ').replace('</Window>', '</base:ScaledWindow>')
        text = text.replace('<Grid>', '<!-- <ScrollViewer/> --><Grid>')
        code, report = self.scan(text)
        self.assertEqual(code, 1, report)

    def test_template_only_scroll_does_not_certify_content(self):
        text = _fixture('<Window.Resources><ControlTemplate><ScrollViewer/></ControlTemplate></Window.Resources>' + BODY)
        code, report = self.scan(text)
        self.assertEqual(code, 1, report)

    def test_nested_button_row_and_conditional_content(self):
        text = _fixture(BODY.replace('<Button Grid.Row="1" Content="Übernehmen"/>',
            '<StackPanel Grid.Row="1" Visibility="{Binding ScopeVisibility}"><Grid><Button Content="Abbrechen"/><StackPanel Orientation="Horizontal"><Button Content="Übernehmen"/></StackPanel></Grid></StackPanel>'))
        code, report = self.scan(text)
        self.assertEqual(code, 1, report)
