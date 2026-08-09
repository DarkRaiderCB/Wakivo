from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BackendError(RuntimeError):
    """The platform refused, or could not provide, a wakelock."""


@dataclass(frozen=True)
class Wants:
    """Which kinds of idle sleep the caller wants held off."""

    system: bool = True
    display: bool = False


class Backend(Protocol):
    """An OS-level wakelock.

    Implementations must be crash-safe: if the process dies for any reason,
    including SIGKILL, the OS must drop the hold on its own. Nothing here may
    mutate persistent system settings -- that is what lid-close handling would
    require, and it is deliberately out of scope.
    """

    name: str

    def acquire(self, wants: Wants, reason: str) -> None: ...

    def release(self) -> None: ...
