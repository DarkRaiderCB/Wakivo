from __future__ import annotations

import argparse
import signal
import sys
import time

from . import __version__
from .backends import BackendError, Wants, get_backend
from .triggers import (
    CommandTrigger,
    IndefiniteTrigger,
    PidTrigger,
    TimerTrigger,
    Trigger,
    TriggerError,
    format_duration,
    parse_duration,
)

LID_NOTE = "closing the lid will still sleep this machine"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wakivo",
        description="Keep this machine awake for as long as a task actually runs.",
        epilog=(
            "examples:\n"
            "  wakivo -- uv run train.py     hold until the command exits\n"
            "  wakivo --pid 41823            hold until that process exits\n"
            "  wakivo 2h                     hold for two hours\n"
            "  wakivo                        hold until Ctrl-C\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "duration",
        nargs="?",
        help="how long to stay awake, e.g. 90s, 20m, 2h, 1h30m",
    )
    parser.add_argument(
        "--pid",
        type=int,
        metavar="PID",
        help="stay awake until this process exits",
    )
    parser.add_argument(
        "-d",
        "--keep-display",
        action="store_true",
        help="also keep the display on (off by default, so the screen still sleeps)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress status output",
    )
    parser.add_argument("--version", action="version", version=f"wakivo {__version__}")
    return parser


def split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split `wakivo [options] -- cmd ...` at the first bare `--`."""
    if "--" not in argv:
        return argv, []
    index = argv.index("--")
    return argv[:index], argv[index + 1 :]


def choose_trigger(args: argparse.Namespace, command: list[str]) -> Trigger:
    given = [
        name
        for name, present in (
            ("a command", bool(command)),
            ("--pid", args.pid is not None),
            ("a duration", args.duration is not None),
        )
        if present
    ]
    if len(given) > 1:
        raise TriggerError(f"pick one release condition, not {' and '.join(given)}")

    if command:
        return CommandTrigger(command)
    if args.pid is not None:
        return PidTrigger(args.pid)
    if args.duration is not None:
        try:
            seconds = parse_duration(args.duration)
        except ValueError as error:
            raise TriggerError(str(error)) from None
        return TimerTrigger(seconds)
    return IndefiniteTrigger()


def main(argv: list[str] | None = None) -> int:
    options, command = split_command(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(options)

    try:
        trigger = choose_trigger(args, command)
        backend = get_backend()
    except TriggerError as error:
        print(f"wakivo: {error}", file=sys.stderr)
        return error.exit_code
    except BackendError as error:
        print(f"wakivo: {error}", file=sys.stderr)
        return 2

    wants = Wants(system=True, display=args.keep_display)
    held = "system sleep + display sleep" if wants.display else "system sleep"

    def on_terminate(signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    previous_term = signal.signal(signal.SIGTERM, on_terminate)

    try:
        backend.acquire(wants, f"wakivo: {trigger.description}")
    except BackendError as error:
        print(f"wakivo: {error}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"wakivo: holding off {held}, {trigger.description}", file=sys.stderr)
        print(f"        note: {LID_NOTE}.", file=sys.stderr)

    started = time.monotonic()
    code = 0
    try:
        code = trigger.wait()
    except KeyboardInterrupt:
        code = 130
    except TriggerError as error:
        print(f"wakivo: {error}", file=sys.stderr)
        code = error.exit_code
    finally:
        backend.release()
        signal.signal(signal.SIGTERM, previous_term)
        if not args.quiet:
            elapsed = format_duration(time.monotonic() - started)
            print(f"\nwakivo: released after {elapsed}", file=sys.stderr)

    return code


if __name__ == "__main__":
    raise SystemExit(main())
