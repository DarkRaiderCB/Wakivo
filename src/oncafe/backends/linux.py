"""Linux wakelock via a systemd-logind idle inhibitor.

The other backends call the platform API directly, because there the API is a
single ctypes call and spawning a child would only add a way to strand the
hold. logind is different: the inhibitor is handed out as a *file descriptor*
over D-Bus, so taking it directly means implementing D-Bus fd passing.
`systemd-inhibit` is the canonical, well-tested client for exactly that, so
this backend drives it as a child process instead.

That would normally give up the guarantee the other backends provide -- an
orphaned child would hold the inhibitor open after oncafe was gone.
PR_SET_PDEATHSIG closes it: the kernel kills the helper the moment this
process dies, so the fd is dropped no matter how oncafe exits, SIGKILL
included.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import signal
import subprocess

from .base import BackendError, Wants

_PR_SET_PDEATHSIG = 1
_STARTUP_GRACE_SECONDS = 0.5

# logind's own IdleAction, and the desktop idle-suspend that honours these
# inhibitors. Deliberately not "sleep": an explicit `systemctl suspend` should
# still work, matching PreventUserIdleSystemSleep on macOS.
_WHAT = "idle"


def _load_libc() -> ctypes.CDLL:
    path = ctypes.util.find_library("c") or "libc.so.6"
    try:
        return ctypes.CDLL(path, use_errno=True)
    except OSError as error:
        raise BackendError(f"could not load libc: {error}") from None


class LinuxBackend:
    name = "systemd-logind"

    def __init__(self) -> None:
        self._inhibit = shutil.which("systemd-inhibit")
        if self._inhibit is None:
            raise BackendError(
                "systemd-inhibit not found -- oncafe needs systemd-logind on Linux"
            )
        # Loaded before the fork: doing it in the child would mean running the
        # dynamic loader after fork, which is not safe.
        self._libc = _load_libc()
        self._process: subprocess.Popen[bytes] | None = None

    def acquire(self, wants: Wants, reason: str) -> None:
        if wants.display:
            raise BackendError(
                "--keep-display is not supported on Linux yet: it needs the "
                "desktop-specific screensaver interfaces rather than logind"
            )

        argv = [
            self._inhibit,
            f"--what={_WHAT}",
            "--who=oncafe",
            f"--why={reason}",
            "--mode=block",
            # cat blocks until its stdin closes, so releasing the hold is just
            # closing a pipe -- no signals, no timeouts, no magic durations.
            "cat",
        ]

        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=self._die_with_parent(os.getpid()),
        )

        # systemd-inhibit fails fast when logind refuses -- no session bus, or
        # polkit denying the inhibitor. Catch that here rather than reporting
        # a hold that was never taken.
        try:
            process.wait(timeout=_STARTUP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._process = process
            return

        detail = ""
        if process.stderr is not None:
            detail = process.stderr.read().decode("utf-8", "replace").strip()
        raise BackendError(
            f"systemd-inhibit exited immediately with code {process.returncode}"
            + (f": {detail}" if detail else "")
        )

    def release(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return

        if process.stdin is not None:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _die_with_parent(self, parent_pid: int):
        libc = self._libc

        def configure() -> None:
            libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
            # If the parent died between fork and prctl, the signal will never
            # arrive and this child would outlive it holding the inhibitor.
            if os.getppid() != parent_pid:
                os._exit(1)

        return configure
