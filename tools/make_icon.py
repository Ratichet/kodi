"""Génère l'icône de l'application à partir de la charte de `ui/styles.py`.

Le dessin reprend le ⬡ de la barre latérale et l'accent rouge de l'interface. Tout
est tracé ici : aucune image extérieure n'entre dans le paquet, et le rendu est
recalculable à l'identique.

    python tools/make_icon.py [--output assets/icon.ico]
"""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent

# Reprises de ui/styles.py : l'icône doit être du même monde que l'interface.
BG_TOP = (26, 26, 46)  # #1a1a2e
BG_BOTTOM = (22, 33, 62)  # #16213e
ACCENT = (233, 69, 96)  # #e94560
ACCENT_LIGHT = (255, 107, 129)  # #ff6b81

# Dessiné en grand puis réduit : les bords obliques du losange et du triangle
# seraient crénelés si on les traçait directement en 32 pixels.
CANVAS = 1024
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _background(size: int) -> Image.Image:
    """Carré à coins arrondis, dégradé vertical."""
    gradient = Image.new("RGB", (1, size))
    for y in range(size):
        ratio = y / max(size - 1, 1)
        gradient.putpixel(
            (0, y),
            tuple(
                round(top + (bottom - top) * ratio)
                for top, bottom in zip(BG_TOP, BG_BOTTOM)
            ),
        )
    gradient = gradient.resize((size, size))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255
    )

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(gradient, (0, 0), mask)
    return canvas


def _hexagon(center: float, radius: float) -> list:
    """Hexagone pointe en haut, comme le ⬡ de la barre latérale."""
    return [
        (
            center + radius * math.cos(math.radians(angle)),
            center - radius * math.sin(math.radians(angle)),
        )
        for angle in range(90, 450, 60)
    ]


def build(size: int = CANVAS) -> Image.Image:
    icon = _background(size)
    draw = ImageDraw.Draw(icon)
    center = size / 2

    # Hexagone plein plutôt qu'un contour : à 16 pixels, un trait fin disparaît.
    draw.polygon(_hexagon(center, size * 0.40), fill=ACCENT)
    draw.polygon(_hexagon(center, size * 0.335), fill=ACCENT_LIGHT)

    # Triangle de lecture évidé dans l'hexagone, en couleur de fond.
    side = size * 0.30
    height = side * math.sqrt(3) / 2
    left = center - height * 0.42
    draw.polygon(
        [
            (left, center - side / 2),
            (left, center + side / 2),
            (left + height, center),
        ],
        fill=BG_BOTTOM,
    )
    return icon


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "assets" / "icon.ico"))
    parser.add_argument(
        "--png", action="store_true", help="écrit aussi un PNG 512 px à côté"
    )
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    master = build()
    # Pillow réduit lui-même vers chaque taille demandée, en Lanczos.
    master.save(output, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    print(f"{output} — {', '.join(f'{s}×{s}' for s in ICON_SIZES)}")

    if args.png:
        preview = output.with_suffix(".png")
        master.resize((512, 512), Image.LANCZOS).save(preview)
        print(f"{preview} — 512×512")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
