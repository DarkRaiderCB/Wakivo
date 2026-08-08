"""Menu-bar / tray artwork, drawn at runtime rather than shipped as assets.

Generating the icon keeps binaries out of the repo and lets the two states be
the same shape at different weights, which reads better at 22px than two
unrelated glyphs.

The colour is a mid grey on purpose. macOS template images -- which invert
themselves for dark menu bars -- are not reachable through pystray, so the one
colour has to stay legible against both a white and a black bar. Grey does;
black or white would vanish on one of them.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

INK = (140, 140, 140, 255)
SIZE = 44


def render(active: bool, size: int = SIZE) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stroke = max(2, size // 16)

    def box(x0: float, y0: float, x1: float, y1: float) -> list[float]:
        return [x0 * size, y0 * size, x1 * size, y1 * size]

    # Cup body, filled when a hold is active and outlined when it is not.
    body = box(0.18, 0.30, 0.66, 0.78)
    draw.rounded_rectangle(
        body,
        radius=size * 0.10,
        fill=INK if active else None,
        outline=INK,
        width=stroke,
    )

    # Handle.
    draw.arc(box(0.58, 0.40, 0.84, 0.66), start=-70, end=90, fill=INK, width=stroke)

    # Saucer.
    draw.line(box(0.10, 0.88, 0.74, 0.88), fill=INK, width=stroke)

    return image
