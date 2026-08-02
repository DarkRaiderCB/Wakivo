from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time

import pytest

from oncafe.backends import BackendError, Wants, get_backend

REASON = "oncafe: test"


def macos_assertions() -> str:
    return subprocess.run(
        ["pmset", "-g", "assertions"], capture_output=True, text=True, check=True
    ).stdout


def windows_requests(section: str) -> list[str]:
    """Entries under one section of `powercfg /requests`, e.g. SYSTEM."""
    output = subprocess.run(
        ["powercfg", "/requests"], capture_output=True, text=True, check=True
    ).stdout

    entries: list[str] = []
    capturing = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and stripped[:-1].isupper():
            capturing = stripped[:-1] == section
            continue
        if capturing and stripped and stripped != "None.":
            entries.append(stripped)
    return entries


def is_elevated() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def linux_inhibitors() -> str:
    return subprocess.run(
        ["systemd-inhibit", "--list"], capture_output=True, text=True, check=True
    ).stdout


needs_pmset = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("pmset") is None,
    reason="pmset is macOS only",
)

needs_logind = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("systemd-inhibit") is None,
    reason="systemd-inhibit is Linux only",
)

needs_powercfg = pytest.mark.skipif(
    sys.platform != "win32" or not is_elevated(),
    reason="powercfg /requests needs an elevated Windows shell",
)


def holder_source(marker: str) -> str:
    return (
        "import sys, time;"
        "sys.path.insert(0, 'src');"
        "from oncafe.backends import get_backend, Wants;"
        "b = get_backend();"
        f"b.acquire(Wants(), {marker!r});"
        "print('held', flush=True);"
        "time.sleep(30)"
    )


def test_a_backend_exists_for_this_platform() -> None:
    backend = get_backend()
    assert backend.name


def test_acquire_and_release_round_trips() -> None:
    # Exercises the real ctypes signatures -- this is what catches a broken
    # IOKit or kernel32 declaration before a user does.
    backend = get_backend()
    backend.acquire(Wants(system=True, display=False), REASON)
    backend.release()


def test_release_is_safe_to_call_twice() -> None:
    backend = get_backend()
    backend.acquire(Wants(), REASON)
    backend.release()
    backend.release()


@needs_pmset
def test_macos_system_hold_is_visible_to_the_os() -> None:
    backend = get_backend()
    backend.acquire(Wants(system=True, display=False), REASON)
    try:
        held = macos_assertions()
        assert REASON in held
        assert "PreventUserIdleSystemSleep" in held
    finally:
        backend.release()
    assert REASON not in macos_assertions()


@needs_pmset
def test_macos_display_flag_adds_a_second_assertion() -> None:
    backend = get_backend()
    backend.acquire(Wants(system=True, display=True), REASON)
    try:
        held = [line for line in macos_assertions().splitlines() if REASON in line]
        kinds = {
            kind
            for kind in ("PreventUserIdleSystemSleep", "PreventUserIdleDisplaySleep")
            if any(kind in line for line in held)
        }
        assert kinds == {"PreventUserIdleSystemSleep", "PreventUserIdleDisplaySleep"}
    finally:
        backend.release()


@needs_pmset
def test_macos_hold_does_not_survive_the_process() -> None:
    # The whole design rests on the OS reclaiming the hold, so that a crash
    # cannot strand the machine awake. Verify with SIGKILL, which gives the
    # child no chance to clean up after itself.
    marker = f"oncafe: kill test {os.getpid()}"
    child = subprocess.Popen(
        [sys.executable, "-c", holder_source(marker)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "held"
        assert marker in macos_assertions()
    finally:
        child.kill()
        child.wait()

    assert marker not in macos_assertions()


@needs_powercfg
def test_windows_system_hold_is_visible_to_the_os() -> None:
    # powercfg reports the holding executable, not our reason string, and the
    # test runner is itself python.exe -- so compare against a baseline rather
    # than matching on a name.
    backend = get_backend()
    baseline = windows_requests("SYSTEM")
    backend.acquire(Wants(system=True, display=False), REASON)
    try:
        assert len(windows_requests("SYSTEM")) > len(baseline)
    finally:
        backend.release()
    assert windows_requests("SYSTEM") == baseline


@needs_powercfg
def test_windows_display_flag_adds_a_display_request() -> None:
    backend = get_backend()
    baseline = windows_requests("DISPLAY")
    backend.acquire(Wants(system=True, display=True), REASON)
    try:
        assert len(windows_requests("DISPLAY")) > len(baseline)
    finally:
        backend.release()
    assert windows_requests("DISPLAY") == baseline


@needs_powercfg
def test_windows_hold_does_not_survive_the_process() -> None:
    # ES_CONTINUOUS is per-thread state, so this checks Windows really does
    # reclaim it when the holding process is killed outright.
    baseline = windows_requests("SYSTEM")
    child = subprocess.Popen(
        [sys.executable, "-c", holder_source(REASON)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "held"
        assert len(windows_requests("SYSTEM")) > len(baseline)
    finally:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(child.pid)], capture_output=True
        )
        child.wait()

    deadline = time.monotonic() + 5
    while len(windows_requests("SYSTEM")) > len(baseline) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert windows_requests("SYSTEM") == baseline


@needs_logind
def test_linux_hold_is_visible_to_logind() -> None:
    backend = get_backend()
    backend.acquire(Wants(system=True, display=False), REASON)
    try:
        assert REASON in linux_inhibitors()
    finally:
        backend.release()
    assert REASON not in linux_inhibitors()


@needs_logind
def test_linux_rejects_keep_display_rather_than_ignoring_it() -> None:
    # Silently not honouring --keep-display would be worse than refusing it.
    backend = get_backend()
    with pytest.raises(BackendError):
        backend.acquire(Wants(system=True, display=True), REASON)


@needs_logind
def test_linux_hold_does_not_survive_the_process() -> None:
    # The inhibitor is held by a systemd-inhibit child, so this checks the
    # PR_SET_PDEATHSIG wiring: SIGKILL here must take the helper with it,
    # rather than orphaning it still holding the lock.
    marker = f"oncafe: kill test {os.getpid()}"
    child = subprocess.Popen(
        [sys.executable, "-c", holder_source(marker)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "held"
        assert marker in linux_inhibitors()
    finally:
        child.kill()
        child.wait()

    deadline = time.monotonic() + 5
    while marker in linux_inhibitors() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert marker not in linux_inhibitors()
