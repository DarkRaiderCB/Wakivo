from __future__ import annotations

import shlex
import subprocess

from .base import TriggerError


class CommandTrigger:
    """Hold the wakelock for exactly as long as a command runs."""

    def __init__(self, argv: list[str]) -> None:
        if not argv:
            raise TriggerError("no command given after `--`")
        self.argv = argv
        self.description = f"until `{shlex.join(argv)}` exits"

    def cancel(self) -> None:
        """Not supported, deliberately.

        This hold is defined as "for as long as the command runs". Ending it
        early would either abandon the command unprotected or kill the user's
        job, and neither is something a Stop button should do quietly. The
        tray app never offers command holds, so nothing calls this.
        """

    def wait(self) -> int:
        try:
            process = subprocess.Popen(self.argv)
        except FileNotFoundError:
            raise TriggerError(f"command not found: {self.argv[0]}", 127) from None
        except PermissionError:
            raise TriggerError(f"not executable: {self.argv[0]}", 126) from None

        while True:
            try:
                return process.wait()
            except KeyboardInterrupt:
                # Ctrl-C already reached the child through the foreground
                # process group; keep waiting so we reap it and report its code.
                continue
