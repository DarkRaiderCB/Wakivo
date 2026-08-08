from __future__ import annotations

import sys

SUPPORTED_PLATFORMS = ("darwin", "win32")
INSTALL_HINT = 'the GUI needs its extra: pipx install "oncafe[gui]"'
LINUX_HINT = "oncafe-gui runs on macOS and Windows only — use the `oncafe` CLI"


def main(argv: list[str] | None = None) -> int:
    # Both checks happen before importing the app, so an unsupported platform
    # or a missing extra produces one clear line rather than a traceback.
    if sys.platform not in SUPPORTED_PLATFORMS:
        print(LINUX_HINT, file=sys.stderr)
        return 2

    try:
        from .app import main as run
    except ImportError:
        print(f"oncafe: {INSTALL_HINT}", file=sys.stderr)
        return 2

    return run(argv)


__all__ = ["main"]
