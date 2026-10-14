#!/usr/bin/env python3
"""Explicit offline XCFramework check; never launched by the ordinary scan.

Uses the normal inventory and its limits. Reads Mach-O/fat/ar bytes, never
executes a target binary. CPU coverage is not an SDK, ABI, link or boot proof.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import plistlib
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ruttla.config import Config  # noqa: E402
from ruttla.context import Context  # noqa: E402
from ruttla.models import GateInputError  # noqa: E402


class UnknownBinary(ValueError):
    """Unsupported, incomplete or inconsistent binary: never a pass."""


def cpu_name(cpu: int, subtype: int) -> str:
    subtype &= 0x00FFFFFF
    known = {(0x100000C, 0): "arm64", (0x100000C, 1): "arm64",
             (0x100000C, 2): "arm64e", (0x1000007, 3): "x86_64",
             (0x1000007, 8): "x86_64h", (7, 3): "i386",
             (12, 9): "armv7", (12, 11): "armv7s"}
    if (cpu, subtype) not in known:
        raise UnknownBinary("unsupported CPU/subtype")
    return known[cpu, subtype]


def architectures(data: memoryview, depth: int = 0) -> set[str]:
    if depth > 3:
        raise UnknownBinary("excessive binary nesting")
    magic = bytes(data[:8])
    thin = {b"\xce\xfa\xed\xfe": ("<", 28), b"\xcf\xfa\xed\xfe": ("<", 32),
            b"\xfe\xed\xfa\xce": (">", 28), b"\xfe\xed\xfa\xcf": (">", 32)}
    if magic[:4] in thin:
        endian, size = thin[magic[:4]]
        if len(data) < size:
            raise UnknownBinary("truncated Mach-O header")
        cpu, subtype, filetype, count, commands = struct.unpack_from(endian + "5I", data, 4)
        if filetype not in (1, 2, 6, 8) or commands > len(data) - size or count > commands // 8:
            raise UnknownBinary("invalid Mach-O load-command bounds")
        return {cpu_name(cpu, subtype)}
    fat = {b"\xca\xfe\xba\xbe": (">", False), b"\xbe\xba\xfe\xca": ("<", False),
           b"\xca\xfe\xba\xbf": (">", True), b"\xbf\xba\xfe\xca": ("<", True)}
    if magic[:4] in fat:
        endian, wide = fat[magic[:4]]
        if len(data) < 8:
            raise UnknownBinary("truncated fat header")
        count = struct.unpack_from(endian + "I", data, 4)[0]
        step = 32 if wide else 20
        table_end = 8 + count * step
        if not 1 <= count <= 64 or table_end > len(data):
            raise UnknownBinary("invalid fat table")
        found: set[str] = set()
        ranges: list[tuple[int, int]] = []
        for i in range(count):
            fmt = "IIQQII" if wide else "IIIII"
            cpu, subtype, offset, size, *_ = struct.unpack_from(endian + fmt, data, 8 + i * step)
            name = cpu_name(cpu, subtype)
            if (name in found or offset < table_end or size == 0 or offset + size > len(data)
                    or any(offset < end and offset + size > start for start, end in ranges)):
                raise UnknownBinary("invalid/overlapping fat slice")
            inner = architectures(data[offset:offset + size], depth + 1)
            if inner != {name}:
                raise UnknownBinary("fat CPU table contradicts its payload")
            ranges.append((offset, offset + size))
            found |= inner
        return found
    if magic == b"!<arch>\n":
        offset = 8
        found = set()
        string_table = b""
        members = 0
        while offset < len(data):
            members += 1
            if members > 100_000 or offset + 60 > len(data) or bytes(data[offset + 58:offset + 60]) != b"`\n":
                raise UnknownBinary("invalid archive member header")
            try:
                name = bytes(data[offset:offset + 16]).decode("ascii").strip()
                size = int(bytes(data[offset + 48:offset + 58]).strip())
            except (ValueError, UnicodeError) as exc:
                raise UnknownBinary("invalid archive name/size") from exc
            start, end = offset + 60, offset + 60 + size
            if size < 0 or end > len(data):
                raise UnknownBinary("truncated archive member")
            payload = data[start:end]
            if name.startswith("#1/"):
                try:
                    length = int(name[3:])
                    if not 0 < length <= size:
                        raise ValueError()
                    name = bytes(payload[:length]).rstrip(b"\0").decode("ascii")
                except (ValueError, UnicodeError) as exc:
                    raise UnknownBinary("invalid BSD archive name") from exc
                payload = payload[length:]
            elif name == "//":
                string_table = bytes(payload)
            elif name.startswith("/") and name[1:].isdigit():
                index = int(name[1:])
                if index >= len(string_table):
                    raise UnknownBinary("missing GNU archive string table")
                name = string_table[index:].split(b"/\n", 1)[0].decode("ascii")
            if name not in ("/", "//", "/SYM64/") and not name.startswith("__.SYMDEF"):
                found |= architectures(payload, depth + 1)
            offset = end + (size % 2)
            if offset > len(data):
                raise UnknownBinary("missing archive alignment byte")
        if not found:
            raise UnknownBinary("archive contains no measured Mach-O objects")
        return found
    raise UnknownBinary("unsupported binary format")


def relative_join(*parts: str) -> str:
    for part in parts:
        if not isinstance(part, str) or not part or "\\" in part:
            raise ValueError("invalid relative XCFramework path")
        path = PurePosixPath(part)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("XCFramework path escapes inventory")
    return str(PurePosixPath(*parts))


def inspect(root: Path, framework: str, max_bytes: int | None = None) -> dict:
    config = Config.load(str(root))
    if max_bytes is not None:
        if max_bytes <= 0:
            raise ValueError("max-file-bytes must be positive")
        config.max_file_bytes = max_bytes
    ctx = Context(str(root), config)
    files = {f.rel: f for f in ctx.all_files()}
    plist = relative_join(framework, "Info.plist")
    report = {"status": "UNMEASURED", "framework": framework,
              "max_file_bytes": config.max_file_bytes, "slices": [], "limits":
              "CPU architectures only; platform, ABI, build, installation, boot and UI are unmeasured"}
    if plist not in files:
        report["reason"] = "Info.plist absent or excluded from inventory"
        return report
    with open(files[plist].path, "rb") as stream:
        metadata = plistlib.load(stream)
    if not isinstance(metadata, dict):
        report["reason"] = "XCFramework metadata is not a dictionary"
        return report
    libraries = metadata.get("AvailableLibraries")
    if not isinstance(libraries, list) or not libraries:
        report["reason"] = "AvailableLibraries absent/invalid"
        return report
    rows = []
    for library in libraries:
        row = {"status": "UNMEASURED"}
        rows.append(row)
        try:
            if not isinstance(library, dict):
                raise ValueError("invalid library entry")
            path = relative_join(framework, library.get("LibraryIdentifier"), library.get("LibraryPath"))
            if path.endswith(".framework"):
                path = relative_join(path, PurePosixPath(path).stem)
            declared = library.get("SupportedArchitectures")
            if (not isinstance(declared, list) or not declared or not all(isinstance(a, str) for a in declared)
                    or len(set(declared)) != len(declared)):
                raise ValueError("SupportedArchitectures absent/invalid")
            row.update(file=path, declared=sorted(declared))
            if path not in files:
                row["reason"] = "binary absent, excluded, symlink alias or over size limit"
                continue
            with open(files[path].path, "rb") as stream:
                data = stream.read(config.max_file_bytes + 1)
            if len(data) > config.max_file_bytes:
                raise UnknownBinary("binary grew beyond size limit")
            actual = architectures(memoryview(data))
            row.update(actual=sorted(actual), status="PASS" if actual == set(declared) else "FAIL")
        except (ValueError, UnicodeError, struct.error) as exc:
            row["reason"] = str(exc)
    report["slices"] = rows
    report["status"] = ("FAIL" if any(r["status"] == "FAIL" for r in rows) else
                        "UNMEASURED" if any(r["status"] == "UNMEASURED" for r in rows) else "PASS")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="explicit scan root; usual inventory exclusions apply")
    parser.add_argument("framework", help="relative .xcframework directory inside root")
    parser.add_argument("--max-file-bytes", type=int, help="explicit override of the ordinary size limit")
    args = parser.parse_args()
    try:
        report = inspect(args.root.resolve(), args.framework, args.max_file_bytes)
    except (OSError, ValueError, plistlib.InvalidFileException, GateInputError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {"PASS": 0, "FAIL": 1, "UNMEASURED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
