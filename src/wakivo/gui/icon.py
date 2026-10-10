"""Menu-bar / tray artwork, drawn at runtime rather than shipped as assets.

Generating the icon keeps binaries out of the repo and lets the two states be
the same shape at different weights, which reads better at 22px than two
unrelated glyphs.

Colour is decided by the caller, because the two platforms solve it
differently. macOS gets a *template* image -- solid black plus alpha, which
the system recolours for light and dark menu bars. Windows has no such
concept, so the app picks black or white from the taskbar theme.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)

# The launcher icon is a different problem from the menu bar one: it sits on
# whatever wallpaper the user has, so it needs its own ground rather than
# borrowing the bar's.
APP_GROUND = (61, 39, 30, 255)
APP_INK = (245, 240, 232, 255)

# Rendered at 2x the usual 22px status bar and downscaled by the toolkit,
# which supersamples the strokes rather than aliasing them.
SIZE = 44


def render(active: bool, ink: tuple[int, int, int, int] = BLACK, size: int = SIZE) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Heavier than looks right at 44px: it is seen at half that, where a thin
    # stroke reads as grey rather than as a line.
    stroke = max(2, round(size / 11))

    def box(x0: float, y0: float, x1: float, y1: float) -> list[float]:
        return [x0 * size, y0 * size, x1 * size, y1 * size]

    # Cup body, filled when a hold is active and outlined when it is not. Kept
    # large in the frame: at 22px a smaller body leaves the outline state with
    # too little interior and it reads as a filled blob.
    draw.rounded_rectangle(
        box(0.12, 0.24, 0.62, 0.74),
        radius=size * 0.10,
        fill=ink if active else None,
        outline=ink,
        width=stroke,
    )

    # Handle. The sweep runs past ±90° on purpose so its ends wrap back into
    # the body -- stopping at ±72° leaves a gap, and the handle then reads as a
    # detached chevron rather than part of the cup.
    draw.arc(box(0.50, 0.34, 0.86, 0.62), start=-105, end=105, fill=ink, width=stroke)

    # Saucer. Carries most of the "cup" reading at small sizes: without it the
    # filled state silhouettes as a rounded blob with a bump.
    draw.line(box(0.08, 0.86, 0.66, 0.86), fill=ink, width=stroke)

    return image


def render_app(size: int = 512) -> Image.Image:
    """The Dock / Start menu icon: the same cup on its own rounded ground."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=size * 0.22, fill=APP_GROUND
    )

    # Outlined rather than filled: a launcher icon should not imply that a
    # hold is currently active.
    cup = render(active=False, ink=APP_INK, size=int(size * 0.72))

    # Centre the ink, not the canvas. The glyph is not centred within its own
    # bounds -- the handle reaches right, the saucer sits low -- so centring
    # the bitmap leaves the cup visibly down and to the left. Invisible at
    # 22px, obvious at 512.
    bounds = cup.getbbox()
    if bounds:
        left, top, right, bottom = bounds
        offset = (
            (size - (right - left)) // 2 - left,
            (size - (bottom - top)) // 2 - top,
        )
    else:
        offset = ((size - cup.width) // 2, (size - cup.height) // 2)

    image.alpha_composite(cup, offset)
    return image


def render_macos(active: bool):
    """Use a native symbol so macOS retains its Retina representations."""
    from AppKit import NSImage

    make_symbol = getattr(
        NSImage, "imageWithSystemSymbolName_accessibilityDescription_", None
    )
    if make_symbol is None:
        return None
    symbol = "cup.and.saucer.fill" if active else "cup.and.saucer"
    image = make_symbol(symbol, "Wakivo")
    if image is not None:
        image.setTemplate_(True)
    return image
