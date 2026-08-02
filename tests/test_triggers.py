from __future__ import annotations

import os
import subprocess
import sys
import threading

import pytest

from oncafe.triggers import CommandTrigger, PidTrigger, TriggerError
from oncafe.triggers.pid import is_alive


def test_command_trigger_returns_the_child_exit_code() -> None:
    assert CommandTrigger([sys.executable, "-c", "raise SystemExit(7)"]).wait() == 7


def test_command_trigger_reports_a_missing_binary_as_127() -> None:
    trigger = CommandTrigger(["oncafe-no-such-binary"])
    with pytest.raises(TriggerError) as caught:
        trigger.wait()
    assert caught.value.exit_code == 127


def test_command_trigger_rejects_an_empty_command() -> None:
    with pytest.raises(TriggerError):
        CommandTrigger([])


def test_command_trigger_describes_itself_with_the_command() -> None:
    assert "echo hi" in CommandTrigger(["echo", "hi"]).description


def test_this_process_is_alive() -> None:
    assert is_alive(os.getpid())


def test_a_reaped_process_is_not_alive() -> None:
    process = subprocess.Popen([sys.executable, "-c", ""])
    process.wait()
    assert not is_alive(process.pid)


@pytest.mark.parametrize("pid", [0, -1])
def test_pid_trigger_rejects_an_invalid_pid(pid: int) -> None:
    with pytest.raises(TriggerError):
        PidTrigger(pid)


def test_pid_trigger_rejects_a_process_that_is_already_gone() -> None:
    process = subprocess.Popen([sys.executable, "-c", ""])
    process.wait()
    with pytest.raises(TriggerError):
        PidTrigger(process.pid)


def test_pid_trigger_releases_when_the_target_exits() -> None:
    # The target is reaped on another thread, because a pid oncafe waits on is
    # never its own child in practice -- and on POSIX an unreaped zombie still
    # answers signal 0, so it would read as alive forever.
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    trigger = PidTrigger(process.pid)
    result: dict[str, int] = {}

    waiter = threading.Thread(target=lambda: result.update(code=trigger.wait()))
    waiter.start()
    process.wait()
    waiter.join(timeout=15)

    assert not waiter.is_alive(), "PidTrigger did not notice the target exiting"
    assert result["code"] == 0


def test_pid_trigger_does_not_kill_the_target() -> None:
    # os.kill(pid, 0) on Windows calls TerminateProcess, so a liveness check
    # written the obvious way would kill the very process being waited on.
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        PidTrigger(process.pid)
        assert is_alive(process.pid)
        assert process.poll() is None
    finally:
        process.kill()
        process.wait()
