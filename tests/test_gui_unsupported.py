"""The Linux path, which is the one place pystray must not be imported.

Everything else about the front end lives in test_gui.py, which skips itself
on Linux -- importing pystray there raises while it hunts for an X display.
`oncafe.gui` itself imports nothing heavier than argparse until it knows the
platform is supported, which is what makes this testable.
"""

from __future__ import annotations

import sys

import pytest

from oncafe import gui

pytestmark = pytest.mark.skipif(
    sys.platform in gui.SUPPORTED_PLATFORMS, reason="checks the unsupported path"
)


def test_declines_to_run_where_there_is_no_tray(capsys) -> None:
    assert gui.main([]) == 2
    assert "CLI" in capsys.readouterr().err


def test_says_which_command_to_use_instead(capsys) -> None:
    gui.main([])
    assert "oncafe" in capsys.readouterr().err
