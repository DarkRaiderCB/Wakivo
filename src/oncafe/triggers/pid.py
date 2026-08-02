from __future__ import annotations

import ctypes
import os
import sys
import threading

from .base import TriggerError

_POLL_SECONDS = 1.0

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


def _is_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, just not ours to signal.
        return True
    return True


def _is_alive_windows(pid: int) -> bool:
    # NOTE: os.kill(pid, 0) on Windows calls TerminateProcess -- it would kill
    # the very process we are trying to wait on. Query the handle instead.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def is_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _is_alive_windows(pid)
    return _is_alive_posix(pid)


class PidTrigger:
    """Hold the wakelock until an already-running process exits."""

    def __init__(self, pid: int) -> None:
        if pid <= 0:
            raise TriggerError(f"not a valid pid: {pid}")
        if not is_alive(pid):
            raise TriggerError(f"no such process: {pid}")
        self.pid = pid
        self.description = f"until pid {pid} exits"
        self._stop = threading.Event()

    def wait(self) -> int:
        while is_alive(self.pid):
            self._stop.wait(_POLL_SECONDS)
        return 0
