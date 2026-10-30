"""Healthy finalized ZIP validation precedes isolated writer mutations."""
from __future__ import annotations

from pathlib import Path
import unittest

from _support import ensure_checks_loaded, make_tree

ensure_checks_loaded()
from ruttla.core import Config, Context, Status
from ruttla.checks.python.archives import check_zip_crc


class ZipCRCTests(unittest.TestCase):
    def test_healthy_then_each_writer_mutation_and_restoration(self):
        healthy = "import zipfile\nwith zipfile.ZipFile(p, 'r') as archive:\n archive.testzip()\n"
        with make_tree({"pack.py": healthy}) as root:
            path = Path(root, "pack.py")
            run = lambda: check_zip_crc(Context(root, Config()))
            self.assertEqual(run().status, Status.PASS)
            for mode in ("w", "a", "x"):
                with self.subTest(mode=mode):
                    path.write_text(healthy.replace("'r'", repr(mode)))
                    result = run()
                    self.assertEqual(result.status, Status.FAIL)
                    self.assertEqual(len(result.findings), 1)
                    self.assertEqual(result.findings[0].line, 3)
            path.write_text(healthy)
            self.assertEqual(run().status, Status.PASS)

    def test_aliases_multiple_contexts_and_keyword_modes(self):
        source = ("from zipfile import ZipFile as Z\n"
                  "with Z(p, mode='a') as writer, Z(q) as reader:\n"
                  " reader.testzip()\n writer.testzip()\n")
        with make_tree({"pack.py": source}) as root:
            result = check_zip_crc(Context(root, Config()))
            self.assertEqual(result.status, Status.FAIL)
            self.assertEqual([f.line for f in result.findings], [4])

    def test_rebinding_dynamic_and_deferred_scope_remain_unmeasured(self):
        for body in [
            "with zipfile.ZipFile(p, mode) as archive:\n archive.testzip()",
            "with zipfile.ZipFile(p, **options) as archive:\n archive.testzip()",
            "with zipfile.ZipFile(p, 'w') as archive:\n archive = foreign\n archive.testzip()",
            "with zipfile.ZipFile(p, 'w') as archive:\n def later():\n  archive.testzip()",
            "with zipfile.ZipFile(p, 'w') as archive:\n callback = lambda: archive.testzip()",
            "with zipfile.ZipFile(p, 'w') as archive:\n lazy = (archive.testzip() for x in xs)",
            "zipfile = foreign\nwith zipfile.ZipFile(p, 'w') as archive:\n archive.testzip()",
        ]:
            with self.subTest(body=body), make_tree({"pack.py": "import zipfile\n" + body}) as root:
                self.assertEqual(check_zip_crc(Context(root, Config())).status, Status.UNMEASURED)

    def test_reader_shadow_and_unrelated_object_do_not_become_writer_findings(self):
        for source in [
            "import zipfile\nwith zipfile.ZipFile(p, 'w') as archive:\n with zipfile.ZipFile(q) as archive:\n  archive.testzip()",
            "import zipfile\nwith zipfile.ZipFile(p, 'w') as archive, zipfile.ZipFile(q) as archive:\n archive.testzip()",
        ]:
            with self.subTest(source=source), make_tree({"pack.py": source}) as root:
                self.assertEqual(check_zip_crc(Context(root, Config())).status, Status.PASS)
        with make_tree({"pack.py": "class ZipFile: pass\nwith ZipFile(p, 'w') as a:\n a.testzip()"}) as root:
            self.assertEqual(check_zip_crc(Context(root, Config())).status, Status.UNMEASURED)


if __name__ == "__main__":
    unittest.main()
