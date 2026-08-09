"""macOS wakelock via IOKit power assertions.

We call IOPMAssertionCreateWithName through ctypes rather than shelling out to
`caffeinate`. Assertions are owned by this process and the kernel drops them
when it exits, so a hard kill can never strand the machine awake -- a child
`caffeinate` could.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from ctypes import POINTER, byref, c_char_p, c_int, c_uint32, c_void_p

from .base import BackendError, Wants

_KERN_SUCCESS = 0
_ASSERTION_LEVEL_ON = 255
_CF_STRING_ENCODING_UTF8 = 0x08000100

_PREVENT_IDLE_SYSTEM_SLEEP = b"PreventUserIdleSystemSleep"
_PREVENT_IDLE_DISPLAY_SLEEP = b"PreventUserIdleDisplaySleep"


def _load_frameworks() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    cf_path = ctypes.util.find_library("CoreFoundation")
    iokit_path = ctypes.util.find_library("IOKit")
    if not cf_path or not iokit_path:
        raise BackendError("could not locate the CoreFoundation and IOKit frameworks")

    cf = ctypes.CDLL(cf_path)
    iokit = ctypes.CDLL(iokit_path)

    cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
    cf.CFStringCreateWithCString.restype = c_void_p
    cf.CFRelease.argtypes = [c_void_p]
    cf.CFRelease.restype = None

    iokit.IOPMAssertionCreateWithName.argtypes = [
        c_void_p,
        c_uint32,
        c_void_p,
        POINTER(c_uint32),
    ]
    iokit.IOPMAssertionCreateWithName.restype = c_int
    iokit.IOPMAssertionRelease.argtypes = [c_uint32]
    iokit.IOPMAssertionRelease.restype = c_int

    return cf, iokit


class MacOSBackend:
    name = "iokit"

    def __init__(self) -> None:
        self._cf, self._iokit = _load_frameworks()
        self._assertions: list[c_uint32] = []

    def acquire(self, wants: Wants, reason: str) -> None:
        types: list[bytes] = []
        if wants.system:
            types.append(_PREVENT_IDLE_SYSTEM_SLEEP)
        if wants.display:
            types.append(_PREVENT_IDLE_DISPLAY_SLEEP)

        try:
            for assertion_type in types:
                self._assertions.append(self._create(assertion_type, reason))
        except BaseException:
            # Never leave a partial set of assertions behind.
            self.release()
            raise

    def release(self) -> None:
        while self._assertions:
            self._iokit.IOPMAssertionRelease(self._assertions.pop())

    def _create(self, assertion_type: bytes, reason: str) -> c_uint32:
        cf_type = self._cf.CFStringCreateWithCString(
            None, assertion_type, _CF_STRING_ENCODING_UTF8
        )
        cf_reason = self._cf.CFStringCreateWithCString(
            None, reason.encode("utf-8"), _CF_STRING_ENCODING_UTF8
        )
        try:
            if not cf_type or not cf_reason:
                raise BackendError("could not allocate CFString for the assertion")

            assertion_id = c_uint32(0)
            result = self._iokit.IOPMAssertionCreateWithName(
                cf_type, _ASSERTION_LEVEL_ON, cf_reason, byref(assertion_id)
            )
            if result != _KERN_SUCCESS:
                name = assertion_type.decode()
                raise BackendError(
                    f"IOPMAssertionCreateWithName({name}) failed "
                    f"with IOReturn 0x{result & 0xFFFFFFFF:08x}"
                )
            return assertion_id
        finally:
            if cf_type:
                self._cf.CFRelease(cf_type)
            if cf_reason:
                self._cf.CFRelease(cf_reason)
