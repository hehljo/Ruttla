"""Method isolation must not be confused with class isolation or a neighbour."""
import unittest

from _support import cli_json, make_tree

CID = "apple.observable_state_mutated_off_main"


def source(annotation):
    return ("import Observation\n@Observable\nfinal class Store {\n"
            " var items: [Int] = []\n" + annotation +
            " func refresh() async {\n let value = await load()\n items = value\n }\n"
            " func load() async -> [Int] { [] }\n}\n")


class MethodIsolationTests(unittest.TestCase):
    def scan(self, text):
        with make_tree({"App/Store.swift": text}) as root:
            return cli_json(root, "--check", CID)

    def test_healthy_method_then_removed_attribute(self):
        for annotation in (" @MainActor\n", " @MainActor public ",
                           ' @MainActor\n @available(iOS 17, *)\n public '):
            with self.subTest(annotation=annotation):
                code, report = self.scan(source(annotation))
                self.assertEqual(code, 0, report)
        code, report = self.scan(source(""))
        self.assertEqual(code, 1, report)

    def test_annotation_on_other_member_does_not_hide_defect(self):
        for neighbour in (" @MainActor func other() {}\n",
                          " @MainActor var other = 0\n",
                          " // @MainActor\n"):
            with self.subTest(neighbour=neighbour):
                code, report = self.scan(source(neighbour))
                self.assertEqual(code, 1, report)
