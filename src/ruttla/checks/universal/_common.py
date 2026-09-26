"""Universelle Checks — Grundsätze A–E aus CLAUDE.md, plattformunabhängig.

A · Branding ist NIE hardcoded
B · Labor-Modus: statisch auswertbares Flag
C · Kein sichtbarer Text im Code (Katalogpflicht)
D · Zustand getrennt vom Laufzeitkram
E · Veröffentlichtes Protokoll ist ein Vertrag

Dazu: Secrets, Gate-Hygiene (Pipe-Falle, tail vor $?), Existenz-vs-Wirkung.

Shared helpers and fixtures of this pack (not a rule module).
"""

from __future__ import annotations

import os
import re

from ruttla.core import Context


SOURCE_EXTS = (
    ".swift", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".cs",
    ".gd", ".kt", ".java", ".go", ".rs", ".vue", ".svelte",
)
MARKUP_EXTS = (".html", ".xaml", ".xml", ".tscn", ".vue", ".svelte")


def _is_git_ignored(ctx: Context, rel: str) -> bool:
    """True, wenn .gitignore den Pfad erfasst. Konservativ: nur exakte Namen
    und Verzeichnispräfixe, keine volle Glob-Semantik."""
    gi = os.path.join(ctx.root, ".gitignore")
    if not os.path.isfile(gi):
        return False
    try:
        with open(gi, "r", encoding="utf-8", errors="replace") as fh:
            entries = [ln.strip() for ln in fh
                       if ln.strip() and not ln.strip().startswith(("#", "!"))]
    except OSError:
        return False
    base = os.path.basename(rel)
    for e in entries:
        e = e.strip("/")
        if e in (base, rel) or rel.startswith(e + "/"):
            return True
        if e.startswith("*") and base.endswith(e.lstrip("*")):
            return True
        if e.endswith("*") and base.startswith(e.rstrip("*")):
            return True
    return False


# ===========================================================================
# A · Branding
# ===========================================================================

def _brand_candidates(ctx: Context) -> list[str]:
    """Markennamen aus dem Profil, sonst aus Projektmetadaten abgeleitet."""
    if ctx.config.brand_names:
        return ctx.config.brand_names
    names: set[str] = set()
    for sf in ctx.files_named("package.json"):
        m = re.search(r'"name"\s*:\s*"([^"]+)"', sf.text)
        if m:
            raw = m.group(1).split("/")[-1]
            for part in re.split(r"[-_.\s]+", raw):
                if len(part) >= 4 and part.isalpha():
                    names.add(part)
    for sf in ctx.files_named("project.godot"):
        m = re.search(r'config/name\s*=\s*"([^"]+)"', sf.text)
        if m:
            for part in re.split(r"[-_.\s]+", m.group(1)):
                if len(part) >= 4 and part.isalpha():
                    names.add(part)
    # Apple: der Anzeigename steht im Target-Build-Setting oder in der
    # Info.plist. PRODUCT_NAME ist meist "$(TARGET_NAME)" — eine Variable,
    # kein Name — und wird deshalb nur als wörtlicher Wert gelesen.
    apple_patterns = (
        r'INFOPLIST_KEY_CFBundleDisplayName\s*=\s*"?([^";$]+?)"?\s*;',
        r'PRODUCT_NAME\s*=\s*"?([^";$]+?)"?\s*;',
    )
    for sf in ctx.all_files():
        values: list[str] = []
        if sf.ext == ".pbxproj":
            for pat in apple_patterns:
                values += [m.group(1) for m in re.finditer(pat, sf.text)]
        elif sf.ext == ".plist":
            values += re.findall(
                r"<key>CFBundleDisplayName</key>\s*<string>([^<$]+)</string>", sf.text)
        for value in values:
            for part in re.split(r"[-_.\s]+", value):
                if len(part) >= 4 and part.isalpha():
                    names.add(part)
    # Generische Wörter taugen nicht als Markenanker.
    generic = {
        "main", "test", "demo", "core", "util", "utils", "common", "shared",
        "client", "server", "front", "back", "site", "root", "base", "lib",
        "project", "sample", "template", "example", "index", "source",
        # Aus echten Projekten nachgetragen: package.json-Namen, die ein
        # Fachwort tragen statt einer Marke.
        "asset", "assets", "studio", "game", "games", "tool", "tools", "app",
        "apps", "web", "site", "data", "code", "next", "node", "view", "views",
        "page", "pages", "type", "types", "model", "models", "store", "state",
        "auth", "user", "users", "admin", "image", "images", "media", "file",
        "files", "text", "task", "tasks", "item", "items", "list", "form",
        "chat", "note", "notes", "docs", "build", "public", "static", "style",
    }
    return sorted(n for n in names if n.lower() not in generic)
