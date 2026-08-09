"""A hold that can be started and stopped, rather than waited out.

The CLI runs to completion: acquire, block until the trigger fires, release,
exit. A tray app needs the opposite shape -- acquire and return, so the menu
stays responsive, then release later because the user asked or because the
trigger fired on its own.

This owns that lifecycle and knows nothing about any UI, which is where its
tests come from. Backends and triggers are shared with the CLI unchanged.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .backends import Backend, Wants, get_backend
from .triggers import Trigger


@dataclass(frozen=True)
class Status:
    """A snapshot of the hold, safe to read from any thread."""

    active: bool
    description: str = ""
    display: bool = False
    remaining: float | None = None
    """Seconds left, when the hold is time-bounded. None means open-ended."""


class HoldController:
    def __init__(
        self,
        backend: Backend | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._backend = backend if backend is not None else get_backend()
        self._on_change = on_change
        self._lock = threading.RLock()
        self._trigger: Trigger | None = None
        self._thread: threading.Thread | None = None
        self._wants = Wants()
        self._ends_at: float | None = None

    def start(self, trigger: Trigger, wants: Wants | None = None) -> None:
        """Take a hold, replacing any hold already running."""
        self.stop()
        wants = wants if wants is not None else Wants()

        with self._lock:
            self._backend.acquire(wants, f"wakivo: {trigger.description}")
            self._trigger = trigger
            self._wants = wants
            # Timer triggers know how long they run; nothing else does, and a
            # countdown is meaningless for them anyway.
            seconds = getattr(trigger, "seconds", None)
            self._ends_at = time.monotonic() + seconds if seconds else None
            self._thread = threading.Thread(
                target=self._wait_then_release,
                args=(trigger,),
                name="wakivo-hold",
                daemon=True,
            )
            self._thread.start()

        self._notify()

    def stop(self) -> None:
        """Release the hold now, if there is one."""
        with self._lock:
            trigger = self._trigger
            thread = self._thread
            if trigger is None:
                return
            trigger.cancel()

        # Joining under the lock would deadlock: the worker needs it to clear
        # state on its way out.
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10)

    def status(self) -> Status:
        with self._lock:
            if self._trigger is None:
                return Status(active=False)
            remaining = None
            if self._ends_at is not None:
                remaining = max(0.0, self._ends_at - time.monotonic())
            return Status(
                active=True,
                description=self._trigger.description,
                display=self._wants.display,
                remaining=remaining,
            )

    def _wait_then_release(self, trigger: Trigger) -> None:
        try:
            trigger.wait()
        finally:
            if self._release_if_current(trigger):
                self._notify()

    def _release_if_current(self, trigger: Trigger) -> bool:
        with self._lock:
            # A newer hold may have replaced this one while we waited; it owns
            # the backend now, so leave it alone.
            if self._trigger is not trigger:
                return False
            self._backend.release()
            self._trigger = None
            self._thread = None
            self._ends_at = None
            return True

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()
