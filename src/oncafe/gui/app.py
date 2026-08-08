"""A menu-bar / tray front end, for people who would rather not use a shell.

Deliberately smaller than the CLI. Anyone who wants to bind a hold to a
specific process already knows what a PID is and is served by `oncafe --pid`;
everyone else wants two things -- keep this awake for a while, or keep it
awake until I say otherwise -- and a picker they do not have to understand.

No power logic lives here. The menu builds a Trigger and hands it to
HoldController, which is the same path the CLI takes to the same backends.
"""

from __future__ import annotations

import sys
import threading

from ..backends import BackendError, Wants
from ..session import HoldController
from ..triggers import IndefiniteTrigger, TimerTrigger
from . import icon as artwork

DURATIONS: tuple[tuple[str, int], ...] = (
    ("15 minutes", 15 * 60),
    ("30 minutes", 30 * 60),
    ("1 hour", 60 * 60),
    ("2 hours", 2 * 60 * 60),
    ("4 hours", 4 * 60 * 60),
)

# Only the countdown needs this; a hold that is open-ended never changes text.
REFRESH_SECONDS = 30


class TrayApp:
    def __init__(self, backend=None) -> None:
        import pystray

        self._pystray = pystray
        # backend is injectable so tests can drive the menu without touching
        # real power state.
        self._controller = HoldController(backend=backend, on_change=self._refresh)
        self._keep_display = False
        self._error: str | None = None
        self._stopping = threading.Event()
        self._icon = pystray.Icon(
            "oncafe",
            artwork.render(active=False),
            "oncafe",
            menu=self._build_menu(),
        )

    # -- menu ---------------------------------------------------------------

    def _build_menu(self):
        item = self._pystray.MenuItem
        menu = self._pystray.Menu

        durations = menu(
            *(item(label, self._hold_for(seconds)) for label, seconds in DURATIONS)
        )

        return menu(
            item(lambda _: self._status_text(), None, enabled=False),
            menu.SEPARATOR,
            item("Keep awake for", durations),
            item("Keep awake until I quit", self._hold_open_ended),
            item("Stop", self._stop, enabled=lambda _: self._is_active()),
            menu.SEPARATOR,
            item(
                "Keep display on",
                self._toggle_display,
                checked=lambda _: self._keep_display,
            ),
            menu.SEPARATOR,
            item("Quit", self._quit),
        )

    def _status_text(self) -> str:
        if self._error is not None:
            return self._error
        status = self._controller.status()
        if not status.active:
            return "Not holding — this computer sleeps normally"
        if status.remaining is not None:
            return f"Awake — {_humanize(status.remaining)} left"
        return "Awake — until you quit"

    def _is_active(self) -> bool:
        return self._controller.status().active

    # -- actions ------------------------------------------------------------

    def _hold_for(self, seconds: int):
        def action(_icon=None, _item=None) -> None:
            self._start(TimerTrigger(seconds))

        return action

    def _hold_open_ended(self, _icon=None, _item=None) -> None:
        self._start(IndefiniteTrigger())

    def _start(self, trigger) -> None:
        try:
            self._controller.start(
                trigger, Wants(system=True, display=self._keep_display)
            )
            self._error = None
        except BackendError as error:
            # Surfaced in the menu rather than a dialog: there is no window to
            # attach one to, and a tray app that silently does nothing is the
            # worst outcome.
            self._error = f"Failed: {error}"
        self._refresh()

    def _stop(self, _icon=None, _item=None) -> None:
        self._controller.stop()
        self._error = None
        self._refresh()

    def _toggle_display(self, _icon=None, _item=None) -> None:
        self._keep_display = not self._keep_display
        # Re-take an active hold so the change applies now rather than next
        # time, which is what a checkbox implies.
        status = self._controller.status()
        if status.active:
            if status.remaining is not None:
                self._start(TimerTrigger(status.remaining))
            else:
                self._start(IndefiniteTrigger())
        self._refresh()

    def _quit(self, _icon=None, _item=None) -> None:
        self._controller.stop()
        self._icon.stop()

    # -- plumbing -----------------------------------------------------------

    def _refresh(self) -> None:
        try:
            self._icon.icon = artwork.render(active=self._is_active())
            self._icon.update_menu()
        except Exception:
            # A refresh failing must never take the app down; the next tick
            # will try again.
            pass

    def _tick(self) -> None:
        while not self._stopping.wait(REFRESH_SECONDS):
            if self._controller.status().remaining is not None:
                self._refresh()

    def run(self) -> None:
        threading.Thread(target=self._tick, name="oncafe-tick", daemon=True).start()
        _use_accessory_activation_policy()
        try:
            self._icon.run()
        finally:
            self._stopping.set()
            self._controller.stop()


def _humanize(seconds: float) -> str:
    """Coarser than the CLI's formatter, which is the point.

    The menu refreshes every 30 seconds, so a ticking seconds counter would be
    wrong most of the time it is on screen. "1h 20m" is what someone glancing
    at a menu bar actually wants.
    """
    total = int(seconds + 0.5)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


def _use_accessory_activation_policy() -> None:
    """Keep the app out of the macOS Dock and the ⌘-Tab switcher.

    A Python process that creates an NSApplication becomes a regular app by
    default, which for something living in the menu bar is wrong.
    """
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    """Entry point proper. Platform and extras are checked in `gui/__init__`."""
    try:
        TrayApp().run()
    except BackendError as error:
        print(f"oncafe: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
