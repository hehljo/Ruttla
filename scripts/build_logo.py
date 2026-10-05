#!/usr/bin/env python3
"""Erzeugt docs/icon/logo.svg aus der Pixelvorlage docs/icon/logo-source.png.

Die Vorlage ist die einzige Quelle; das SVG wird nie von Hand bearbeitet.
Zwei Ebenen aus dem Alphakanal: die halbtransparente Schüttelkopie (Geisterbild)
und die deckende Form darüber. Farbe und Deckkraft stehen nur im Stilblock,
damit der Dunkelmodus eine Zeile bleibt.

Nur für Maintainer: braucht ``pip install potracer pillow`` (kein Laufzeit-Extra).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "icon" / "logo-source.png"
TARGET = ROOT / "docs" / "icon" / "logo.svg"

# Alphagrenzen, gemessen an der Vorlage vom 05.10.2026: deckende Fläche 251–255,
# Geisterbild um 78, Kantenglättung dazwischen. Die Mitte der Lücke trennt sauber.
SOLID_ALPHA = 165
GHOST_ALPHA = 30
PADDING_RATIO = 0.06

STYLE = """<style>
.logo { fill: #C92A2A; }
.ghost { opacity: 0.3; }
@media (prefers-color-scheme: dark) { .logo { fill: #FF6B6B; } }
</style>"""


def _trace(mask, offset: tuple[int, int]) -> str:
    import potrace  # Vordergrund = dunkel, deshalb Maske als 0 auf 255

    ox, oy = offset

    def pt(p) -> str:
        return f"{p.x + ox:.1f},{p.y + oy:.1f}"

    parts: list[str] = []
    for curve in potrace.Bitmap(mask).trace(turdsize=8, opttolerance=0.4):
        seg = [f"M{pt(curve.start_point)}"]
        for s in curve.segments:
            if s.is_corner:
                seg.append(f"L{pt(s.c)}L{pt(s.end_point)}")
            else:
                seg.append(f"C{pt(s.c1)} {pt(s.c2)} {pt(s.end_point)}")
        parts.append("".join(seg) + "Z")
    return "".join(parts)


def build() -> str:
    try:
        from PIL import Image
    except ImportError:
        sys.exit("build_logo: pip install potracer pillow")

    image = Image.open(SOURCE).convert("RGBA")
    alpha = image.getchannel("A")
    bbox = alpha.point(lambda a: 255 if a > GHOST_ALPHA else 0).getbbox()
    if bbox is None:
        sys.exit(f"build_logo: {SOURCE} ist vollständig transparent")
    alpha = alpha.crop(bbox)
    width, height = alpha.size
    side = max(width, height)
    pad = round(side * PADDING_RATIO)
    view = side + 2 * pad
    offset = (pad + (side - width) // 2, pad + (side - height) // 2)

    ghost = _trace(alpha.point(lambda a: 0 if a > GHOST_ALPHA else 255), offset)
    solid = _trace(alpha.point(lambda a: 0 if a > SOLID_ALPHA else 255), offset)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" role="img">\n'
        f"{STYLE}\n"
        f'<path class="logo ghost" fill-rule="evenodd" d="{ghost}"/>\n'
        f'<path class="logo" fill-rule="evenodd" d="{solid}"/>\n'
        "</svg>\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="nur prüfen, ob logo.svg aktuell ist")
    args = parser.parse_args()
    svg = build()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != svg:
            print(f"veraltet: {TARGET.relative_to(ROOT)} — scripts/build_logo.py ausführen")
            return 1
        return 0
    TARGET.write_text(svg, encoding="utf-8")
    print(f"{TARGET.relative_to(ROOT)}: {len(svg)} Bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
