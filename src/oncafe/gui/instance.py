"""One tray icon per machine.

Launching twice gave two icons and two independent holds, with nothing to tell
them apart: stopping from one menu left the other still holding, and the tray
looked broken. Since the app has no window to raise, a second launch has
nothing useful to do, so it exits.

The lock is an exclusive lock on a file, held for the life of the process and
released by the kernel when it ends -- the same property the wakelock backends
rely on. Nothing to clean up after a crash, and no stale pid file to
misinterpret.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_handle = None


def lock_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_RUNTIME_DIR") or Path.home())
    return root / "oncafe" / "gui.lock"


def acquire(path: Path | None = None) -> bool:
    """True if this process now owns the single-instance lock."""
    global _handle

    path = path if path is not None else lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")

    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False

    # Kept open deliberately: closing it would drop the lock.
    _handle = handle
    return True
