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
