from __future__ import annotations

import sys

from .base import Backend, BackendError, Wants

__all__ = ["Backend", "BackendError", "Wants", "get_backend"]


def get_backend() -> Backend:
    """Return the wakelock backend for the running platform."""
    if sys.platform == "darwin":
        from .macos import MacOSBackend

        return MacOSBackend()
    if sys.platform == "win32":
        from .windows import WindowsBackend

        return WindowsBackend()
    if sys.platform.startswith("linux"):
        from .linux import LinuxBackend

        return LinuxBackend()
    raise BackendError(
        f"no wakelock backend for {sys.platform!r} yet "
        "-- oncafe supports macOS, Windows and Linux"
    )
