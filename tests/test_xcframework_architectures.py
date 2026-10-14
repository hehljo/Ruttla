"""Binary CPU controls; missing/excluded/unsupported inputs stay unmeasured."""
import importlib.util
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest

from _support import REPO

spec = importlib.util.spec_from_file_location("xcframework_probe", REPO / "scripts/check_xcframework_architectures.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def macho(cpu=0x100000C, subtype=0):
    return struct.pack("<8I", 0xFEEDFACF, cpu, subtype, 1, 0, 0, 0, 0)


def archive(data, name="file.o/"):
    header = (f"{name:<16}{0:<12}{0:<6}{0:<6}{0:<8}{len(data):<10}`\n").encode("ascii")
    return b"!<arch>\n" + header + data + (b"\n" if len(data) % 2 else b"")


def fat(arm, x86):
    return (struct.pack(">II", 0xCAFEBABE, 2)
            + struct.pack(">IIIII", 0x100000C, 0, 48, len(arm), 0)
            + struct.pack(">IIIII", 0x1000007, 3, 48 + len(arm), len(x86), 0)
            + arm + x86)


def tree(root, binary, declared=("arm64",), name="arbitrary-name"):
    framework = root / "Acme.xcframework"
    (framework / name).mkdir(parents=True)
    metadata = {"AvailableLibraries": [{"LibraryIdentifier": name,
        "LibraryPath": "lib.a", "SupportedArchitectures": list(declared), "SupportedPlatform": "ios"}]}
    (framework / "Info.plist").write_bytes(plistlib.dumps(metadata))
    (framework / name / "lib.a").write_bytes(binary)
    return framework


class XCFrameworkArchitectures(unittest.TestCase):
    def test_healthy_then_single_metadata_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            framework = tree(root, archive(macho()), name="ios-arm64_x86_64-simulator")
            healthy = probe.inspect(root, "Acme.xcframework")
            self.assertEqual(healthy["status"], "PASS", healthy)
            path = framework / "Info.plist"
            data = plistlib.loads(path.read_bytes())
            data["AvailableLibraries"][0]["SupportedArchitectures"].append("x86_64")
            path.write_bytes(plistlib.dumps(data))
            defective = probe.inspect(root, "Acme.xcframework")
            self.assertEqual(defective["status"], "FAIL", defective)
            self.assertEqual(defective["slices"][0]["actual"], ["arm64"])

    def test_binary_formats(self):
        arm, x86 = macho(), macho(0x1000007, 3)
        for data, expected in [(arm, {"arm64"}), (archive(x86), {"x86_64"}),
                               (fat(archive(arm), archive(x86)), {"arm64", "x86_64"}),
                               (archive(arm + b"\0", "#1/0"), None)]:
            with self.subTest(expected=expected):
                if expected is None:
                    with self.assertRaises(probe.UnknownBinary):
                        probe.architectures(memoryview(data))
                else:
                    self.assertEqual(probe.architectures(memoryview(data)), expected)
        bsd = archive(b"file.o\0\0" + arm, "#1/8")
        self.assertEqual(probe.architectures(memoryview(bsd)), {"arm64"})
        gnu = archive(b"file.o/\n", "//") + archive(arm, "/0")[8:]
        self.assertEqual(probe.architectures(memoryview(gnu)), {"arm64"})
        universal64 = (struct.pack(">II", 0xCAFEBABF, 2)
            + struct.pack(">IIQQII", 0x100000C, 0, 72, len(arm), 0, 0)
            + struct.pack(">IIQQII", 0x1000007, 3, 72 + len(arm), len(x86), 0, 0)
            + arm + x86)
        self.assertEqual(probe.architectures(memoryview(universal64)), {"arm64", "x86_64"})

    def test_unknown_boundaries(self):
        for binary in [b"!<arch>\n", b"not a binary", macho()[:15], archive(macho())[:-3]]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tree(root, binary)
                self.assertEqual(probe.inspect(root, "Acme.xcframework")["status"], "UNMEASURED")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            framework = tree(root, archive(macho()))
            path = framework / "arbitrary-name/lib.a"
            path.write_bytes(archive(macho() + b"\0" * 5000))
            oversized = probe.inspect(root, "Acme.xcframework", 2000)
            self.assertEqual(oversized["status"], "UNMEASURED")
            self.assertEqual(len(oversized["slices"]), 1)
            self.assertIn("size limit", oversized["slices"][0]["reason"])
            path.unlink()
            self.assertEqual(probe.inspect(root, "Acme.xcframework")["status"], "UNMEASURED")
            path.write_bytes(archive(macho()))
            (root / ".ruttla.toml").write_text('[gate]\nexclude=["**/*.a"]\n')
            self.assertEqual(probe.inspect(root, "Acme.xcframework")["status"], "UNMEASURED")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            framework = tree(root, archive(macho()))
            (framework / "Info.plist").write_bytes(plistlib.dumps([]))
            self.assertEqual(probe.inspect(root, "Acme.xcframework")["status"], "UNMEASURED")

    def test_no_hidden_build_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree(root / "build", archive(macho()))
            self.assertEqual(probe.inspect(root, "build/Acme.xcframework")["status"], "UNMEASURED")

    def test_fat_payload_contradiction(self):
        with self.assertRaises(probe.UnknownBinary):
            probe.architectures(memoryview(fat(archive(macho()), archive(macho()))))

    def test_path_escape(self):
        for path in ["../secret", "/etc", "some/../../etc", "some\\else"]:
            with self.assertRaises(ValueError):
                probe.relative_join("Acme.xcframework", path)


if __name__ == "__main__":
    unittest.main()
