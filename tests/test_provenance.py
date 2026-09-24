"""Public-provenance guard (P00-T001, NFR-010).

Private project names, the maintainer's bundle-ID prefix and a formerly
committed Apple Team ID must never re-enter the working tree. The deny-list
stores only truncated SHA-256 hashes of lower-cased tokens, so this file does
not itself publish what it protects.

Add a new entry:
    python -c "import hashlib; print(hashlib.sha256(b'<token>').hexdigest()[:24])"
"""

from __future__ import annotations

import hashlib
import os
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DENY = {
    "5d609a9734f81c6623ef71c3",
    "d479a9ed2f89ade03814ec61",
    "8dbec0bf81ab29bd19eba0ca",
    "92c9b9926d13da7e848b2fd5",
    "b2c8a5d11da87a865050a297",
    "3d869d228aa1aaa38cf607c7",
    "bc55d2a9d4ca98f4d65a0900",
    "9a0d11710344ed71d9e0f5c8",
    "a5c7f986b139e685fd5c1eb2",
    "384995348d92aeda4959cc9a",
    "e4d020b5faf35ec51fd2dda9",
}
# The maintainer handle is legitimate where ownership is stated.
OWNER = "2c8df694b0532f1c1771e549"
OWNER_ALLOWED = {
    "NOTICE",
    ".github/CODEOWNERS",
    "pyproject.toml",
    "README.md",
    "README.de.md",
    "docs/integrations/github-actions.md",
    "src/ruttla/update.py",
}

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "build", "dist", ".ruff_cache"}
TOKEN = re.compile(r"[a-z0-9]+")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:24]


def tracked_text_files() -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for name in filenames:
            path = Path(dirpath, name)
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if b"\0" in data[:4096]:
                continue
            out.append(path)
    return out


def find_hits(paths: list[Path], deny: set[str]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        rel = path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.name
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for token in set(TOKEN.findall(text)):
            digest = _digest(token)
            if digest in deny or (digest == OWNER and rel not in OWNER_ALLOWED):
                hits.append(f"{rel}: token hash {digest}")
    return sorted(hits)


class ProvenanceTests(unittest.TestCase):
    def test_no_private_identifiers_in_working_tree(self) -> None:
        hits = find_hits(tracked_text_files(), DENY)
        self.assertEqual(hits, [], "private provenance found:\n" + "\n".join(hits))

    def test_guard_detects_a_planted_identifier(self) -> None:
        # Sabotage probe: the guard must be able to turn red, and stay green
        # on a clean file. A synthetic token stands in for a private name.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dirty = Path(tmp, "dirty.md")
            dirty.write_text("Observed in Plantedprojectname on 2026-01-01.\n", encoding="utf-8")
            clean = Path(tmp, "clean.md")
            clean.write_text("Observed in a real macOS app on 2026-01-01.\n", encoding="utf-8")
            deny = {_digest("plantedprojectname")}
            self.assertEqual(len(find_hits([dirty], deny)), 1)
            self.assertEqual(find_hits([clean], deny), [])


if __name__ == "__main__":
    unittest.main()
