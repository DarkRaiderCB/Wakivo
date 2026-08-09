from __future__ import annotations

from typing import Protocol


class TriggerError(RuntimeError):
    """The trigger could not be set up, or could not start its work.

    `exit_code` lets a trigger pick the shell convention that fits: 127 for a
    command that does not exist, 126 for one that is not executable.
    """

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class Trigger(Protocol):
    """Decides when the wakelock is no longer needed.

    Triggers are deliberately independent of backends: any trigger composes
    with any platform, and a new release condition is a new file here rather
    than a change to the wakelock code.
    """

    description: str

    def wait(self) -> int:
        """Block until the hold should end, and return an exit code."""
        ...

    def cancel(self) -> None:
        """Ask `wait` to return early. Safe to call from another thread.

        The CLI never needs this -- it waits until the trigger fires and then
        exits. A tray app does: "Stop" has to end a hold that would otherwise
        run for hours.
        """
        ...
