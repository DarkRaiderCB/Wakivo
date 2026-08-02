from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

from oncafe.backends import Wants, get_backend

REASON = "oncafe: test"


def macos_assertions() -> str:
    return subprocess.run(
        ["pmset", "-g", "assertions"], capture_output=True, text=True, check=True
    ).stdout


needs_pmset = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("pmset") is None,
    reason="pmset is macOS only",
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
        [
            sys.executable,
            "-c",
            "import sys, time;"
            "sys.path.insert(0, 'src');"
            "from oncafe.backends import get_backend, Wants;"
            "b = get_backend();"
            f"b.acquire(Wants(), {marker!r});"
            "print('held', flush=True);"
            "time.sleep(30)",
        ],
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
