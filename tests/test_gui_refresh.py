"""Redraw accounting.

Rebuilding the menu is by far the most expensive thing the tray app does --
it happens inside the toolkit, on the UI thread, and it is what a click feels
as a stall. Everything on our side is microseconds. So the thing worth testing
is not speed but *count*: one redraw per user action, none when nothing
changed.
"""

from __future__ import annotations

import sys

import pytest

from oncafe import gui
from oncafe.backends import BackendError

from .test_session import FakeBackend

# Before importing pystray: see the note in test_gui.py.
if sys.platform not in gui.SUPPORTED_PLATFORMS:
    pytest.skip("the tray front end targets macOS and Windows", allow_module_level=True)

pytest.importorskip("pystray", reason="the GUI extra is not installed")


class CountingIcon:
    def __init__(self) -> None:
        self.menu_rebuilds = 0
        self.icon_redraws = 0
        self._icon = None

    @property
    def icon(self):
        return self._icon

    @icon.setter
    def icon(self, value) -> None:
        self._icon = value
        self.icon_redraws += 1

    def update_menu(self) -> None:
        self.menu_rebuilds += 1

    def stop(self) -> None:
        pass


@pytest.fixture
def app():
    from oncafe.gui.app import TrayApp

    tray = TrayApp(backend=FakeBackend())
    tray._icon = CountingIcon()
    yield tray
    tray._controller.stop()


def test_one_menu_rebuild_per_action(app) -> None:
    app._hold_open_ended()
    assert app._icon.menu_rebuilds == 1

    app._stop()
    assert app._icon.menu_rebuilds == 2


def test_no_redraw_when_nothing_changed(app) -> None:
    app._hold_open_ended()
    before = app._icon.menu_rebuilds

    app._refresh()
    app._refresh()

    assert app._icon.menu_rebuilds == before


def test_the_ticker_does_not_redraw_a_steady_countdown(app) -> None:
    # The countdown is coarse, so most 30s ticks land on the same text and
    # must not rebuild the menu for it.
    app._hold_for(4 * 60 * 60)()
    before = app._icon.menu_rebuilds

    for _ in range(5):
        app._refresh()

    assert app._icon.menu_rebuilds == before


def test_the_icon_is_only_redrawn_when_the_state_flips(app) -> None:
    app._hold_for(900)()
    after_start = app._icon.icon_redraws
    assert after_start == 1

    # Still active, so the artwork is unchanged even though the menu is not.
    app._hold_for(1800)()
    assert app._icon.icon_redraws == after_start

    app._stop()
    assert app._icon.icon_redraws == after_start + 1


def test_toggling_display_while_idle_still_redraws_the_checkbox(app) -> None:
    # The status line reads the same either way, so keying the cache on text
    # alone would silently drop this.
    before = app._icon.menu_rebuilds
    app._toggle_display()
    assert app._icon.menu_rebuilds == before + 1


def test_a_stale_error_is_not_shown_after_a_successful_start(app) -> None:
    def refuse(wants, reason):
        raise BackendError("nope")

    working = app._controller._backend.acquire
    app._controller._backend.acquire = refuse
    app._hold_open_ended()
    assert "Failed" in app._status_text()

    app._controller._backend.acquire = working
    app._hold_open_ended()
    assert "Failed" not in app._status_text()
