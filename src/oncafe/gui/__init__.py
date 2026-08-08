from __future__ import annotations

import argparse
import sys

SUPPORTED_PLATFORMS = ("darwin", "win32")
INSTALL_HINT = 'the GUI needs its extra: pipx install "oncafe[gui]"'
LINUX_HINT = "oncafe-gui runs on macOS and Windows only — use the `oncafe` CLI"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oncafe-gui",
        description="Keep this computer awake, from the menu bar.",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="create a double-clickable launcher, so this needs no terminal",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="remove the launcher",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Checked before importing anything, so an unsupported platform or a
    # missing extra produces one clear line rather than a traceback.
    if sys.platform not in SUPPORTED_PLATFORMS:
        print(LINUX_HINT, file=sys.stderr)
        return 2

    if args.install or args.uninstall:
        return _manage(args)

    from .instance import acquire

    if not acquire():
        # Not an error: the app is already there, doing its job. A second icon
        # with its own separate hold would be the failure.
        print("oncafe: already running — look for the cup in the menu bar")
        return 0

    try:
        from .app import main as run
    except ImportError:
        print(f"oncafe: {INSTALL_HINT}", file=sys.stderr)
        return 2

    return run()


def _manage(args: argparse.Namespace) -> int:
    try:
        from .launcher import LauncherError, install, uninstall
    except ImportError:
        print(f"oncafe: {INSTALL_HINT}", file=sys.stderr)
        return 2

    try:
        if args.uninstall:
            removed = uninstall()
            for path in removed:
                print(f"removed {path}")
            if not removed:
                print("nothing to remove")
            return 0

        for path in install():
            print(f"created {path}")
    except (LauncherError, OSError) as error:
        print(f"oncafe: {error}", file=sys.stderr)
        return 1
    return 0


__all__ = ["main", "build_parser", "SUPPORTED_PLATFORMS"]
