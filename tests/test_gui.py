from __future__ import annotations

import sys

import pytest

from wakivo import gui
from wakivo.backends import BackendError, Wants

from .test_session import FakeBackend, wait_until

# Skipped before pystray is imported at all: on a headless Linux runner it
# raises Xlib.error.DisplayNameError while selecting a backend, which
# importorskip does not catch, and collection fails outright.
if sys.platform not in gui.SUPPORTED_PLATFORMS:
    pytest.skip("the tray front end targets macOS and Windows", allow_module_level=True)

pystray = pytest.importorskip("pystray", reason="the GUI extra is not installed")

from wakivo.gui import icon  # noqa: E402  -- needs the extra imported above
from wakivo.gui.app import DURATIONS  # noqa: E402

@pytest.fixture
def app(request):
    from wakivo.gui.app import TrayApp

    # A distinct name per test: see the note in TrayApp.__init__ about window
    # class collisions on Windows.
    tray = TrayApp(backend=FakeBackend(), name=f"wakivo-{request.node.name}")
    yield tray
    tray._controller.stop()


def colours(image) -> list[tuple[int, tuple[int, int, int, int]]]:
    return image.getcolors(1 << 24) or []


@pytest.mark.parametrize("ink", [(0, 0, 0, 255), (255, 255, 255, 255)])
def test_the_icon_is_drawn_in_solid_ink(ink) -> None:
    # It was mid grey once, to survive both light and dark bars, and looked
    # washed out on each. macOS gets a template image and Windows picks a
    # colour from the taskbar theme, so neither has to be a compromise now.
    opaque = {rgba[:3] for _, rgba in colours(icon.render(True, ink=ink)) if rgba[3] > 200}
    assert opaque == {ink[:3]}


def test_the_two_icon_states_are_distinguishable() -> None:
    def coverage(image) -> int:
        return sum(count for count, rgba in colours(image) if rgba[3] > 128)

    idle, holding = icon.render(False), icon.render(True)
    assert idle.tobytes() != holding.tobytes()
    # The filled cup must be the *active* one; inverted, the tray would lie.
    assert coverage(holding) > coverage(idle)


def test_macos_draws_black_and_lets_the_system_recolour_it() -> None:
    from wakivo.gui.app import _ink
    from wakivo.gui.icon import BLACK, WHITE

    if sys.platform == "darwin":
        assert _ink() == BLACK
    else:
        assert _ink() in (BLACK, WHITE)


def test_menu_offers_only_the_two_modes(app) -> None:
    # The whole premise of the GUI is that it stays small. Anyone needing to
    # scope a hold to a process is served by the CLI.
    labels = [str(entry).splitlines()[0] for entry in app._build_menu()]
    assert "Keep awake until I quit" in labels
    assert any(label.startswith("Keep awake for") for label in labels)
    assert not any("pid" in label.lower() or "process" in label.lower() for label in labels)


def test_status_text_tracks_the_hold(app) -> None:
    assert "Not holding" in app._status_text()

    app._hold_open_ended()
    assert app._status_text() == "Awake — until you quit"

    app._stop()
    assert "Not holding" in app._status_text()


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


def test_picking_a_duration_replaces_a_running_hold(app) -> None:
    backend = app._controller._backend

    app._hold_open_ended()
    app._hold_for(900)()

    assert backend.calls == ["acquire", "release", "acquire"]
    assert backend.held


def test_the_display_option_reads_as_a_modifier(app) -> None:
    # It changes nothing until a hold starts, so the label must not present
    # itself as a live state.
    labels = [str(entry).splitlines()[0] for entry in app._build_menu()]
    display = next(label for label in labels if "display" in label.lower())
    assert display.lower().startswith("also")


def test_keep_display_applies_to_the_hold_already_running(app) -> None:
    backend = app._controller._backend

    app._hold_open_ended()
    assert backend.wants[-1] == Wants(system=True, display=False)

    app._toggle_display()
    assert app._keep_display
    assert backend.wants[-1] == Wants(system=True, display=True)


def test_toggling_display_while_idle_takes_no_hold(app) -> None:
    backend = app._controller._backend
    app._toggle_display()
    assert app._keep_display
    assert backend.calls == []


def test_a_refused_backend_is_reported_in_the_menu(app) -> None:
    def refuse(wants, reason):
        raise BackendError("polkit said no")

    app._controller._backend.acquire = refuse
    app._hold_open_ended()

    assert "Failed" in app._status_text()
    assert "polkit said no" in app._status_text()
    assert not app._controller.status().active


def test_an_expired_timer_returns_the_menu_to_idle(app) -> None:
    app._hold_for(1)()
    app._controller._trigger.cancel()
    assert wait_until(lambda: "Not holding" in app._status_text())


def test_quit_releases_the_hold(app) -> None:
    backend = app._controller._backend
    app._hold_open_ended()
    app._icon.stop = lambda: None
    app._quit()
    assert not backend.held


def marks(app) -> dict[str, bool]:
    """Which mutually-exclusive entries currently show as selected."""

    def walk(entries) -> dict[str, bool]:
        found: dict[str, bool] = {}
        for entry in entries:
            if entry.submenu is not None:
                found.update(walk(entry.submenu))
            elif entry.radio:
                found[str(entry).splitlines()[0]] = bool(entry.checked)
        return found

    return walk(list(app._build_menu()))


def test_nothing_is_marked_while_idle(app) -> None:
    assert not any(marks(app).values())


def test_the_running_duration_is_marked(app) -> None:
    app._hold_for(60 * 60)()
    assert marks(app)["1 hour"]
    assert not marks(app)["2 hours"]
    assert not marks(app)["Keep awake until I quit"]


def test_the_mark_moves_when_the_duration_changes(app) -> None:
    app._hold_for(60 * 60)()
    app._hold_for(2 * 60 * 60)()

    current = marks(app)
    assert current["2 hours"]
    assert not current["1 hour"]


def test_an_open_ended_hold_marks_its_own_entry(app) -> None:
    app._hold_open_ended()
    current = marks(app)
    assert current["Keep awake until I quit"]
    assert not any(current[label] for label, _ in DURATIONS)


def test_stopping_clears_the_mark(app) -> None:
    app._hold_for(900)()
    app._stop()
    assert not any(marks(app).values())


def test_an_expired_hold_clears_the_mark(app) -> None:
    app._hold_for(1)()
    app._controller._trigger.cancel()
    assert wait_until(lambda: not any(marks(app).values()))


def test_toggling_the_display_keeps_the_mark(app) -> None:
    # It re-takes the same hold, so the marked entry must not move.
    app._hold_for(2 * 60 * 60)()
    app._toggle_display()
    assert marks(app)["2 hours"]
