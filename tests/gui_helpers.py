"""Wait for asynchronous UI updates using the platform's event loop."""

import sys
import threading

from .test_session import wait_until as poll_until


def wait_until(predicate, timeout=5.0):
    def check():
        if sys.platform == "darwin":
            from Foundation import NSDate, NSRunLoop

            NSRunLoop.mainRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.01)
            )
        return predicate()

    return poll_until(check, timeout)


class CountingIcon:
    def __init__(self, *args, **kwargs) -> None:
        self.menu_rebuilds = 0
        self.icon_redraws = 0
        self._icon = None
        self.update_threads = []
        self._visible = False

    @property
    def icon(self):
        return self._icon

    @icon.setter
    def icon(self, value) -> None:
        self.update_threads.append(threading.current_thread())
        self._icon = value
        self.icon_redraws += 1

    def update_menu(self) -> None:
        self.update_threads.append(threading.current_thread())
        self.menu_rebuilds += 1

    @property
    def visible(self):
        return self._visible

    @visible.setter
    def visible(self, value):
        self.update_threads.append(threading.current_thread())
        self._visible = value

    def stop(self) -> None:
        pass
