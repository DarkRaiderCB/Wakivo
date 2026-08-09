"""Linux wakelock via systemd-logind, plus GNOME's session inhibitor.

The other backends call the platform API directly, because there the API is a
single ctypes call and spawning a child would only add a way to strand the
hold. logind is different: the inhibitor is handed out as a *file descriptor*
over D-Bus, so taking it directly means implementing D-Bus fd passing.
`systemd-inhibit` is the canonical, well-tested client for exactly that, so
this backend drives it as a child process instead.

That would normally give up the guarantee the other backends provide -- an
orphaned child would hold the inhibitor open after wakivo was gone.
PR_SET_PDEATHSIG closes it: the kernel kills the helper the moment this
process dies, so the fd is dropped no matter how wakivo exits, SIGKILL
included.

Two holds, not one
------------------
A logind inhibitor alone is not enough under GNOME. Measured on Debian/GNOME:
with wakivo holding `sleep:idle` in *block* mode -- enough that `systemctl
suspend` was refused outright -- gsd-power still suspended the machine 112
seconds into the hold. GNOME runs its own idle policy and consults its own
session inhibitors, which live on the session bus and are entirely separate
from logind's.

So on a GNOME session we take both: logind for the path that governs headless
and non-GNOME systems, and `gnome-session-inhibit` for the one GNOME actually
checks. Neither subsumes the other -- a Debian server has no gnome-session at
all.
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

# Tried in order, first one that is permitted wins.
#
# Blocking "sleep" additionally stops Suspend() calls, which covers desktops
# whose power daemon we have not measured -- but it needs the
# org.freedesktop.login1.inhibit-block-sleep polkit action, which is denied
# without an active seat session. Headless servers and CI runners have no such
# session and are refused outright.
#
# Blocking "idle" alone is granted broadly and covers logind's own IdleAction,
# which is exactly what governs those headless machines. It is a weaker hold
# on a desktop, but GNOME is handled by its own inhibitor below regardless.
_LOGIND_WHAT_PREFERENCES = ("idle:sleep", "idle")

# GNOME: "suspend" only, deliberately not "idle". GNOME's idle inhibitor also
# suppresses screen blanking and locking, and screen-off is wakivo's default.
_GNOME_WHAT = "suspend"


def _load_libc() -> ctypes.CDLL:
    path = ctypes.util.find_library("c") or "libc.so.6"
    try:
        return ctypes.CDLL(path, use_errno=True)
    except OSError as error:
        raise BackendError(f"could not load libc: {error}") from None


def _in_gnome_session() -> bool:
    """True when this process is inside a GNOME session with a session bus."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if "gnome" not in desktop.lower():
        return False
    return bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))


class LinuxBackend:
    name = "systemd-logind"

    def __init__(self) -> None:
        self._systemd_inhibit = shutil.which("systemd-inhibit")
        if self._systemd_inhibit is None:
            raise BackendError(
                "systemd-inhibit not found -- wakivo needs systemd-logind on Linux"
            )
        self._gnome_inhibit = shutil.which("gnome-session-inhibit")
        # Loaded before the fork: running the dynamic loader in the child
        # after fork is not safe.
        self._libc = _load_libc()
        self._holders: list[subprocess.Popen[bytes]] = []

    def acquire(self, wants: Wants, reason: str) -> None:
        if wants.display:
            raise BackendError(
                "--keep-display is not supported on Linux yet: it needs the "
                "desktop-specific screensaver interfaces rather than logind"
            )

        try:
            self._acquire_logind(reason)

            if _in_gnome_session():
                if self._gnome_inhibit is None:
                    raise BackendError(
                        "this is a GNOME session, where a logind inhibitor alone "
                        "does not prevent suspend, but gnome-session-inhibit was "
                        "not found -- install gnome-session-bin"
                    )
                self._spawn(
                    # Space-separated, not --opt=value: gnome-session-inhibit
                    # parses argv with exact string comparisons rather than
                    # GLib, so "--app-id=wakivo" matches no option and falls
                    # through to the COMMAND position, where it tries to
                    # execute it. systemd-inhibit does accept --what=.
                    [
                        self._gnome_inhibit,
                        "--app-id", "wakivo",
                        "--reason", reason,
                        "--inhibit", _GNOME_WHAT,
                        "cat",
                    ]
                )
        except BaseException:
            # Never leave a partial set of holds behind.
            self.release()
            raise

    def _acquire_logind(self, reason: str) -> None:
        last: BackendError | None = None
        for what in _LOGIND_WHAT_PREFERENCES:
            try:
                self._spawn(
                    [
                        self._systemd_inhibit,
                        f"--what={what}",
                        "--who=wakivo",
                        f"--why={reason}",
                        "--mode=block",
                        # cat blocks until its stdin closes, so releasing a
                        # hold is just closing a pipe -- no signals, no
                        # timeouts, no magic durations.
                        "cat",
                    ]
                )
                return
            except BackendError as error:
                last = error
        assert last is not None
        raise last

    def release(self) -> None:
        holders, self._holders = self._holders, []
        for process in reversed(holders):
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

    def _spawn(self, argv: list[str]) -> None:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=self._die_with_parent(os.getpid()),
        )

        # These fail fast when refused -- no session bus, or polkit denying the
        # inhibitor. Catch it here rather than reporting a hold never taken.
        try:
            process.wait(timeout=_STARTUP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._holders.append(process)
            return

        detail = ""
        if process.stderr is not None:
            detail = process.stderr.read().decode("utf-8", "replace").strip()
        raise BackendError(
            f"{os.path.basename(argv[0])} exited immediately with code "
            f"{process.returncode}" + (f": {detail}" if detail else "")
        )

    def _die_with_parent(self, parent_pid: int):
        libc = self._libc

        def configure() -> None:
            libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
            # If the parent died between fork and prctl, the signal will never
            # arrive and this child would outlive it holding the inhibitor.
            if os.getppid() != parent_pid:
                os._exit(1)

        return configure
