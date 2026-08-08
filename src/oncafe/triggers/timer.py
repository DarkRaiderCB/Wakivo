from __future__ import annotations

import re
import threading

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_TOKEN = re.compile(r"(\d+(?:\.\d+)?)([smhd]?)")


def parse_duration(text: str) -> float:
    """Parse `90s`, `20m`, `2h`, `1h30m`, or a bare number of seconds."""
    raw = text.strip().lower()
    if not raw:
        raise ValueError("empty duration")

    total = 0.0
    position = 0
    for match in _TOKEN.finditer(raw):
        if match.start() != position:
            break
        position = match.end()
        total += float(match.group(1)) * _UNIT_SECONDS[match.group(2) or "s"]

    if position != len(raw):
        raise ValueError(f"could not parse duration: {text!r}")
    if total <= 0:
        raise ValueError("duration must be greater than zero")
    return total


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


class TimerTrigger:
    """Hold the wakelock for a fixed duration."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.description = f"for {format_duration(seconds)}"
        self._stop = threading.Event()

    def wait(self) -> int:
        self._stop.wait(self.seconds)
        return 0

    def cancel(self) -> None:
        self._stop.set()


class IndefiniteTrigger:
    """Hold the wakelock until interrupted."""

    description = "until interrupted (Ctrl-C)"

    def __init__(self) -> None:
        self._stop = threading.Event()

    def wait(self) -> int:
        # Waiting in slices keeps Ctrl-C responsive on Windows, where an
        # untimed wait swallows the interrupt.
        while not self._stop.wait(0.5):
            pass
        return 0

    def cancel(self) -> None:
        self._stop.set()
