from __future__ import annotations

import os
import sys

import pytest

from wakivo.cli import build_parser, choose_trigger, main, split_command
from wakivo.triggers import (
    CommandTrigger,
    IndefiniteTrigger,
    PidTrigger,
    TimerTrigger,
    TriggerError,
)


def parse(argv: list[str]):
    return build_parser().parse_args(argv)


@pytest.mark.parametrize(
    ("argv", "options", "command"),
    [
        ([], [], []),
        (["-q"], ["-q"], []),
        (["--"], [], []),
        (["-q", "--", "echo", "hi"], ["-q"], ["echo", "hi"]),
        (["--", "--", "x"], [], ["--", "x"]),
        (["--", "-q"], [], ["-q"]),
    ],
)
def test_splits_at_the_first_bare_separator(
    argv: list[str], options: list[str], command: list[str]
) -> None:
    assert split_command(argv) == (options, command)


def test_flags_after_the_separator_belong_to_the_command() -> None:
    # `-d` here is the wrapped command's flag, not wakivo's.
    options, command = split_command(["-d", "--", "ls", "-d"])
    assert options == ["-d"]
    assert command == ["ls", "-d"]


def test_defaults_to_holding_until_interrupted() -> None:
    assert isinstance(choose_trigger(parse([]), []), IndefiniteTrigger)


def test_selects_a_timer_from_a_duration() -> None:
    trigger = choose_trigger(parse(["2h"]), [])
    assert isinstance(trigger, TimerTrigger)
    assert trigger.seconds == 7200


def test_selects_a_pid_trigger() -> None:
    trigger = choose_trigger(parse(["--pid", str(os.getpid())]), [])
    assert isinstance(trigger, PidTrigger)


def test_selects_a_command_trigger() -> None:
    trigger = choose_trigger(parse([]), ["echo", "hi"])
    assert isinstance(trigger, CommandTrigger)


@pytest.mark.parametrize(
    ("argv", "command"),
    [
        (["2h", "--pid", "1"], []),
        (["2h"], ["echo", "hi"]),
        (["--pid", "1"], ["echo", "hi"]),
        (["2h", "--pid", "1"], ["echo", "hi"]),
    ],
)
def test_rejects_more_than_one_release_condition(
    argv: list[str], command: list[str]
) -> None:
    with pytest.raises(TriggerError):
        choose_trigger(parse(argv), command)


def test_surfaces_a_bad_duration_as_a_trigger_error() -> None:
    with pytest.raises(TriggerError):
        choose_trigger(parse(["5x"]), [])


def test_end_to_end_timer_holds_and_releases() -> None:
    assert main(["-q", "1s"]) == 0


def test_end_to_end_propagates_the_command_exit_code() -> None:
    assert main(["-q", "--", sys.executable, "-c", "raise SystemExit(3)"]) == 3


def test_end_to_end_reports_a_missing_command_as_127() -> None:
    assert main(["-q", "--", "wakivo-no-such-binary"]) == 127


def test_end_to_end_rejects_a_bad_duration_as_2() -> None:
    assert main(["-q", "5x"]) == 2
