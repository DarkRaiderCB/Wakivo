"""A menu-bar / tray front end, for people who would rather not use a shell.

Deliberately smaller than the CLI. Anyone who wants to bind a hold to a
specific process already knows what a PID is and is served by `wakivo --pid`;
everyone else wants two things -- keep this awake for a while, or keep it
awake until I say otherwise -- and a picker they do not have to understand.

No power logic lives here. The menu builds a Trigger and hands it to
HoldController, which is the same path the CLI takes to the same backends.
"""

from __future__ import annotations

import sys
import threading
from contextlib import contextmanager

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

# Which menu entry is marked as running. Durations identify themselves by their
# length, so this needs to be something no duration can equal.
OPEN_ENDED = "open-ended"


class TrayApp:
    def __init__(self, backend=None, name: str = "wakivo") -> None:
        import pystray

        self._pystray = pystray
        # backend is injectable so tests can drive the menu without touching
        # real power state.
        self._controller = HoldController(backend=backend, on_change=self._refresh)
        self._keep_display = False
        self._choice: int | str | None = None
        self._error: str | None = None
        self._stopping = threading.Event()
        # What the tray is currently showing, so _refresh can skip work.
        self._shown_icon: tuple | None = None
        self._shown: tuple | None = None
        self._batching = 0
        # pystray's win32 backend derives a window class name from this plus
        # the object's address, and an Icon that never runs never unregisters
        # it. Two Icons in one process can then collide, so the name is
        # settable -- tests make one per case.
        self._icon = pystray.Icon(
            name,
            artwork.render(active=False),
            "wakivo",
            menu=self._build_menu(),
        )

    # -- menu ---------------------------------------------------------------

    def _build_menu(self):
        item = self._pystray.MenuItem
        menu = self._pystray.Menu

        # Marked rather than disabled. Extending a hold is a normal thing to
        # want, and greying the other durations out would make it a two-step
        # job -- stop, reopen, pick -- with the machine unprotected in between.
        # So they stay live, and the mark says which one is running.
        durations = menu(
            *(
                item(
                    label,
                    self._hold_for(seconds),
                    checked=lambda _, seconds=seconds: self._choice == seconds,
                    radio=True,
                )
                for label, seconds in DURATIONS
            )
        )

        return menu(
            item(lambda _: self._status_text(), None, enabled=False),
            menu.SEPARATOR,
            item("Keep awake for", durations),
            item(
                "Keep awake until I quit",
                self._hold_open_ended,
                checked=lambda _: self._choice == OPEN_ENDED,
                radio=True,
            ),
            item("Stop", self._stop, enabled=lambda _: self._is_active()),
            menu.SEPARATOR,
            # "Also" on purpose. This is a modifier for the next hold, not a
            # live state: ticking it while idle changes nothing until a hold
            # starts, and a bare "Keep display on ☑" sitting above a sleeping
            # screen reads as a lie.
            item(
                "Also keep the display on",
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
            return "Not holding, this computer sleeps normally"
        if status.remaining is not None:
            return f"Awake, {_humanize(status.remaining)} left"
        return "Awake, until you quit"

    def _is_active(self) -> bool:
        return self._controller.status().active

    # -- actions ------------------------------------------------------------

    def _hold_for(self, seconds: int):
        def action(_icon=None, _item=None) -> None:
            self._start(TimerTrigger(seconds), seconds)

        return action

    def _hold_open_ended(self, _icon=None, _item=None) -> None:
        self._start(IndefiniteTrigger(), OPEN_ENDED)

    def _start(self, trigger, choice: int | str) -> None:
        # Cleared first: starting the hold notifies, and that refresh would
        # otherwise redraw the menu still showing the previous error.
        self._error = None
        with self._batched():
            try:
                self._controller.start(
                    trigger, Wants(system=True, display=self._keep_display)
                )
                self._choice = choice
            except BackendError as error:
                # Surfaced in the menu rather than a dialog: there is no window
                # to attach one to, and a tray app that silently does nothing
                # is the worst outcome.
                self._error = f"Failed: {error}"

    def _stop(self, _icon=None, _item=None) -> None:
        self._error = None
        with self._batched():
            self._controller.stop()

    def _toggle_display(self, _icon=None, _item=None) -> None:
        self._keep_display = not self._keep_display
        # Re-take an active hold so the change applies now rather than next
        # time, which is what a checkbox implies.
        status = self._controller.status()
        if status.active:
            # Keeps whichever entry was marked; the hold is the same one, it is
            # only being re-taken so the display flag applies now.
            if status.remaining is not None:
                self._start(TimerTrigger(status.remaining), self._choice)
            else:
                self._start(IndefiniteTrigger(), self._choice)
        self._refresh()

    def _quit(self, _icon=None, _item=None) -> None:
        self._controller.stop()
        self._icon.stop()

    # -- plumbing -----------------------------------------------------------

    @contextmanager
    def _batched(self):
        """Collapse the redraws of a multi-step action into one.

        Replacing a hold goes active → idle → active, because the controller
        releases the old one before taking the new. Drawing each step blinks
        the icon and rebuilds the menu three times for what the user
        experiences as a single click.
        """
        self._batching += 1
        try:
            yield
        finally:
            self._batching -= 1
        self._refresh()

    def _refresh(self) -> None:
        """Push state to the tray, but only what actually changed.

        Both of these are expensive in a way nothing else here is: rebuilding
        the NSMenu and the NSImage happens inside the toolkit, on the UI
        thread, and it is what makes a click feel slow. Everything on our side
        of the line is microseconds.

        Being a no-op when nothing changed also means callers need not reason
        about whether the controller already notified -- calling this twice
        costs nothing.
        """
        if self._batching:
            return

        active = self._is_active()
        if not active:
            # Covers a timer running out on its own as well as Stop.
            self._choice = None
        # Ink is recomputed rather than cached so a light/dark switch is picked
        # up by the next tick, without watching for theme notifications.
        ink = _ink()
        # Everything the menu renders, so a checkbox change is not missed just
        # because the status line happens to read the same.
        shown = (active, self._status_text(), self._keep_display, self._choice)

        try:
            if (active, ink) != self._shown_icon:
                self._icon.icon = artwork.render(active=active, ink=ink)
                self._mark_template_image()
                self._shown_icon = (active, ink)
            if shown != self._shown:
                self._shown = shown
                self._icon.update_menu()
        except Exception:
            # A refresh failing must never take the app down, and the cache
            # must not claim a state we failed to draw.
            self._shown_icon = None
            self._shown = None

    def _tick(self) -> None:
        while not self._stopping.wait(REFRESH_SECONDS):
            if self._controller.status().remaining is not None:
                self._refresh()

    def _mark_template_image(self) -> None:
        """Ask macOS to recolour the icon for the menu bar it sits in.

        pystray builds a plain NSImage, so the icon would render exactly as
        drawn -- black, and invisible on a dark menu bar. Marking that image as
        a template makes the system use only its alpha and paint it black or
        white to match, which is what every native menu bar item does.

        This reaches for a pystray private attribute, so it is guarded: if the
        internals move, the icon is merely drawn as-is rather than broken.
        """
        if sys.platform != "darwin":
            return
        try:
            image = getattr(self._icon, "_icon_image", None)
            if image is not None:
                image.setTemplate_(True)
        except Exception:
            pass

    def _on_ready(self, icon) -> None:
        icon.visible = True
        # The NSImage does not exist until the icon is on screen, so this is
        # the first moment the template flag can be set.
        self._mark_template_image()

    def run(self) -> None:
        threading.Thread(target=self._tick, name="wakivo-tick", daemon=True).start()
        _use_accessory_activation_policy()
        _release_own_console()
        try:
            self._icon.run(setup=self._on_ready)
        finally:
            self._stopping.set()
            self._controller.stop()


def _release_own_console() -> None:
    """Drop a console window that exists only because we were launched.

    Launching from the Start menu leaves an empty terminal sitting behind the
    tray icon for as long as the app runs. Rather than chase which layer
    allocated it -- the shortcut, the launcher shim, or the interpreter --
    hand it back.

    Only when we are the sole process attached to it. Typing `wakivo-gui` in a
    terminal shares that terminal with the shell, and detaching from it there
    would be rude and confusing.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        processes = (ctypes.c_uint32 * 4)()
        attached = kernel32.GetConsoleProcessList(processes, 4)
        if attached == 1:
            kernel32.FreeConsole()
    except Exception:
        pass


def _ink() -> tuple[int, int, int, int]:
    """The colour to draw the icon in.

    macOS always gets black, because the image is marked as a template and the
    system recolours it. Windows has no equivalent, so the taskbar theme has to
    be read and matched -- and it defaults to dark, hence white when unknown.
    """
    if sys.platform != "win32":
        return artwork.BLACK
    return artwork.BLACK if _windows_taskbar_is_light() else artwork.WHITE


def _windows_taskbar_is_light() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
        return bool(value)
    except (OSError, ImportError):
        return False


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
        print(f"wakivo: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
