from __future__ import annotations

import ctypes
import os
import sys
import threading

from .base import TriggerError

_POLL_SECONDS = 1.0

_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WAIT_TIMEOUT = 0x00000102
_ERROR_ACCESS_DENIED = 5

_kernel32 = None


def _is_alive_posix(pid: int) -> bool:
    # Caveat: a zombie -- exited but not yet reaped by its parent -- still
    # answers signal 0, so it reads as alive until the parent collects it.
    # That is correct for our purpose: the pid stays allocated until then, and
    # anything oncafe is asked to wait on has a parent that will reap it.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, just not ours to signal.
        return True
    return True


def _load_kernel32():
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # A HANDLE is pointer-sized. Without these declarations ctypes assumes a
    # C int and truncates it on 64-bit Windows, so every later call on the
    # handle fails and a live process looks dead.
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _is_alive_windows(pid: int) -> bool:
    # NOTE: os.kill(pid, 0) on Windows calls TerminateProcess -- it would kill
    # the very process we are trying to wait on. Query the handle instead.
    global _kernel32
    if _kernel32 is None:
        _kernel32 = _load_kernel32()

    access = _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION
    handle = _kernel32.OpenProcess(access, False, pid)
    if not handle:
        # Access denied means the process is there, we just cannot open it.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED

    try:
        # WAIT_TIMEOUT means the process handle is still unsignalled, i.e. it
        # is running. This avoids GetExitCodeProcess's STILL_ACTIVE ambiguity,
        # where a process exiting with code 259 looks alive forever.
        return _kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        _kernel32.CloseHandle(handle)


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
        while is_alive(self.pid) and not self._stop.is_set():
            self._stop.wait(_POLL_SECONDS)
        return 0

    def cancel(self) -> None:
        self._stop.set()
