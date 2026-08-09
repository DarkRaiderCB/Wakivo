"""Regenerate the README icon from the same code the app draws with.

    uv run python docs/make_icon.py

Committed as a file because README images have to be fetchable by URL --
GitHub and PyPI both render the README, and neither can run the drawing code.
Generating it here rather than hand-drawing one keeps it from drifting away
from what actually appears in the menu bar.
"""

from pathlib import Path

from wakivo.gui.icon import render_app

OUTPUT = Path(__file__).parent / "wakivo.png"

if __name__ == "__main__":
    # 256 so it stays crisp on a high-DPI screen while displayed around 96px.
    render_app(256).save(OUTPUT)
    print(f"wrote {OUTPUT}")
