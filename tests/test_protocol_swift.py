"""Serialization evidence must belong to the enum being reported."""

from pathlib import Path
import tempfile
import unittest

from ruttla.core import Config, Context, Status
from _support import ensure_checks_loaded


class SwiftProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_checks_loaded()

    def scan(self, source):
        from ruttla.checks.universal.protocol import check_protocol_enum

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Models.swift").write_text(source, encoding="utf-8")
            return check_protocol_enum(Context(root=directory, config=Config()))

    def test_healthy_unrelated_enums_are_unmeasured(self):
        result = self.scan(
            "enum Selection: String { case session, persistent }\n"
            "enum Category { case movies, shows }\n"
            "enum Store { static let decoder = JSONDecoder() }\n"
            "struct Payload: Codable { let name: String }\n"
        )
        self.assertEqual(result.status, Status.UNMEASURED)
        self.assertEqual(result.findings, [])

    def test_mutation_only_reports_enum_with_serialization_evidence(self):
        result = self.scan(
            "enum Selection: String, Codable { case session, persistent }\n"
            "enum Category { case movies, shows }\n"
            "enum Store { static let decoder = JSONDecoder() }\n"
            "struct Payload: Codable {\n"
            "  let name: String\n"
            "  enum CodingKeys: String, CodingKey { case name }\n}\n"
        )
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(len(result.findings), 1)
        self.assertIn("'Selection'", result.findings[0].message)
        self.assertEqual(result.findings[0].line, 1)

    def test_mutation_extension_is_bound_to_named_enum(self):
        result = self.scan(
            "enum Category { case movies, shows }\n"
            "private enum WireValue: String { case text, image }\n"
            "extension WireValue: Swift.Decodable {}\n"
        )
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(len(result.findings), 1)
        self.assertIn("'WireValue'", result.findings[0].message)
        self.assertEqual(result.findings[0].line, 2)


if __name__ == "__main__":
    unittest.main()
