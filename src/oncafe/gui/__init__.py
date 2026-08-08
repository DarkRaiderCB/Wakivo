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
        "--startup",
        action="store_true",
        help="with --install, also start it at login",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="remove the launcher, including the login item",
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

    if args.startup:
        print("oncafe: --startup only means something with --install", file=sys.stderr)
        return 2

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

        for path in install(startup=args.startup):
            print(f"created {path}")
        if args.startup:
            print("it will also start at login")
    except (LauncherError, OSError) as error:
        print(f"oncafe: {error}", file=sys.stderr)
        return 1
    return 0


__all__ = ["main", "build_parser", "SUPPORTED_PLATFORMS"]
