"""Windows wakelock via SetThreadExecutionState.

The execution state is *per thread*: it is dropped the moment the thread that
set it exits. So the flags are set on a dedicated thread that parks until
release, rather than on whichever thread happened to call acquire().
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from .base import BackendError, Wants

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


class WindowsBackend:
    name = "set-thread-execution-state"

    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
        self._kernel32.SetThreadExecutionState.restype = wintypes.DWORD

        self._stop = threading.Event()
        self._settled = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: str | None = None

    def acquire(self, wants: Wants, reason: str) -> None:
        flags = ES_CONTINUOUS
        if wants.system:
            flags |= ES_SYSTEM_REQUIRED
        if wants.display:
            flags |= ES_DISPLAY_REQUIRED

        # Fresh events per acquire. Reusing them means a second acquire finds
        # _stop already set from the previous release, so the holding thread
        # clears the state and exits immediately -- a hold that silently is
        # not one. The CLI acquires once and exits; a tray app does this
        # repeatedly.
        self._stop = threading.Event()
        self._settled = threading.Event()
        self._error = None

        self._thread = threading.Thread(
            target=self._hold,
            args=(flags,),
            name="wakivo-wakelock",
            daemon=True,
        )
        self._thread.start()
        self._settled.wait()
        if self._error is not None:
            raise BackendError(self._error)

    def release(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _hold(self, flags: int) -> None:
        previous = self._kernel32.SetThreadExecutionState(flags)
        if previous == 0:
            errno = ctypes.get_last_error()
            self._error = f"SetThreadExecutionState failed (error {errno})"
            self._settled.set()
            return

        self._settled.set()
        try:
            self._stop.wait()
        finally:
            # Must run on this thread -- the state belongs to it.
            self._kernel32.SetThreadExecutionState(ES_CONTINUOUS)
