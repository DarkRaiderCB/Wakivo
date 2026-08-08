from __future__ import annotations

import sys

import pytest

from oncafe import gui
from oncafe.backends import BackendError, Wants

from .test_session import FakeBackend, wait_until

pystray = pytest.importorskip("pystray", reason="the GUI extra is not installed")

needs_tray = pytest.mark.skipif(
    sys.platform not in gui.SUPPORTED_PLATFORMS,
    reason="the tray front end targets macOS and Windows",
)


@pytest.fixture
def app():
    from oncafe.gui.app import TrayApp

    tray = TrayApp(backend=FakeBackend())
    yield tray
    tray._controller.stop()


@needs_tray
def test_menu_offers_only_the_two_modes(app) -> None:
    # The whole premise of the GUI is that it stays small. Anyone needing to
    # scope a hold to a process is served by the CLI.
    labels = [str(entry).splitlines()[0] for entry in app._build_menu()]
    assert "Keep awake until I quit" in labels
    assert any(label.startswith("Keep awake for") for label in labels)
    assert not any("pid" in label.lower() or "process" in label.lower() for label in labels)


@needs_tray
def test_status_text_tracks_the_hold(app) -> None:
    assert "Not holding" in app._status_text()

    app._hold_open_ended()
    assert app._status_text() == "Awake — until you quit"

    app._stop()
    assert "Not holding" in app._status_text()


@needs_tray
@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (2 * 60 * 60, "Awake — 2h left"),
        (90 * 60, "Awake — 1h 30m left"),
        (15 * 60, "Awake — 15m left"),
    ],
)
def test_a_duration_shows_a_countdown(app, seconds: int, expected: str) -> None:
    # Coarse on purpose: the menu refreshes every 30s, so a seconds counter
    # would be stale for most of the time it is visible.
    app._hold_for(seconds)()
    assert app._status_text() == expected


@needs_tray
def test_picking_a_duration_replaces_a_running_hold(app) -> None:
    backend = app._controller._backend

    app._hold_open_ended()
    app._hold_for(900)()

    assert backend.calls == ["acquire", "release", "acquire"]
    assert backend.held


@needs_tray
def test_the_display_option_reads_as_a_modifier(app) -> None:
    # It changes nothing until a hold starts, so the label must not present
    # itself as a live state.
    labels = [str(entry).splitlines()[0] for entry in app._build_menu()]
    display = next(label for label in labels if "display" in label.lower())
    assert display.lower().startswith("also")


@needs_tray
def test_keep_display_applies_to_the_hold_already_running(app) -> None:
    backend = app._controller._backend

    app._hold_open_ended()
    assert backend.wants[-1] == Wants(system=True, display=False)

    app._toggle_display()
    assert app._keep_display
    assert backend.wants[-1] == Wants(system=True, display=True)


@needs_tray
def test_toggling_display_while_idle_takes_no_hold(app) -> None:
    backend = app._controller._backend
    app._toggle_display()
    assert app._keep_display
    assert backend.calls == []


@needs_tray
def test_a_refused_backend_is_reported_in_the_menu(app) -> None:
    def refuse(wants, reason):
        raise BackendError("polkit said no")

    app._controller._backend.acquire = refuse
    app._hold_open_ended()

    assert "Failed" in app._status_text()
    assert "polkit said no" in app._status_text()
    assert not app._controller.status().active


@needs_tray
def test_an_expired_timer_returns_the_menu_to_idle(app) -> None:
    app._hold_for(1)()
    app._controller._trigger.cancel()
    assert wait_until(lambda: "Not holding" in app._status_text())


@needs_tray
def test_quit_releases_the_hold(app) -> None:
    backend = app._controller._backend
    app._hold_open_ended()
    app._icon.stop = lambda: None
    app._quit()
    assert not backend.held


@pytest.mark.skipif(
    sys.platform in gui.SUPPORTED_PLATFORMS, reason="checks the unsupported path"
)
def test_declines_to_run_where_there_is_no_tray(capsys) -> None:
    assert gui.main([]) == 2
    assert "CLI" in capsys.readouterr().err
