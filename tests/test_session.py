from __future__ import annotations

import threading
import time

import pytest

from wakivo.backends import Wants
from wakivo.session import HoldController
from wakivo.triggers import IndefiniteTrigger, TimerTrigger


class FakeBackend:
    """Records what the controller asks of a backend, in order."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.reasons: list[str] = []
        self.wants: list[Wants] = []
        self._lock = threading.Lock()

    def acquire(self, wants: Wants, reason: str) -> None:
        with self._lock:
            self.calls.append("acquire")
            self.reasons.append(reason)
            self.wants.append(wants)

    def release(self) -> None:
        with self._lock:
            self.calls.append("release")

    @property
    def held(self) -> bool:
        with self._lock:
            return self.calls.count("acquire") > self.calls.count("release")


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_starts_idle() -> None:
    controller = HoldController(backend=FakeBackend())
    assert controller.status() == controller.status()
    assert not controller.status().active


def test_start_acquires_and_reports_the_hold() -> None:
    backend = FakeBackend()
    controller = HoldController(backend=backend)

    controller.start(IndefiniteTrigger(), Wants(system=True, display=True))
    try:
        status = controller.status()
        assert status.active
        assert status.display
        assert "interrupted" in status.description
        assert backend.calls == ["acquire"]
        # The reason reaches the OS, so it should name the trigger.
        assert status.description in backend.reasons[0]
    finally:
        controller.stop()


def test_stop_releases() -> None:
    backend = FakeBackend()
    controller = HoldController(backend=backend)

    controller.start(IndefiniteTrigger())
    controller.stop()

    assert not controller.status().active
    assert backend.calls == ["acquire", "release"]


def test_stop_is_safe_when_idle() -> None:
    backend = FakeBackend()
    controller = HoldController(backend=backend)
    controller.stop()
    controller.stop()
    assert backend.calls == []


def test_a_timer_releases_itself_when_it_expires() -> None:
    backend = FakeBackend()
    controller = HoldController(backend=backend)

    controller.start(TimerTrigger(0.2))

    assert wait_until(lambda: not controller.status().active)
    assert backend.calls == ["acquire", "release"]


def test_a_timer_reports_time_remaining() -> None:
    controller = HoldController(backend=FakeBackend())

    controller.start(TimerTrigger(60))
    try:
        remaining = controller.status().remaining
        assert remaining is not None
        assert 55 < remaining <= 60
    finally:
        controller.stop()


def test_an_open_ended_hold_has_no_countdown() -> None:
    controller = HoldController(backend=FakeBackend())

    controller.start(IndefiniteTrigger())
    try:
        assert controller.status().remaining is None
    finally:
        controller.stop()


def test_starting_again_replaces_the_previous_hold() -> None:
    # The tray menu has no "stop first" step -- picking a new duration while
    # one is running has to just work, and must not leak the old hold.
    backend = FakeBackend()
    controller = HoldController(backend=backend)

    controller.start(TimerTrigger(60))
    controller.start(TimerTrigger(120))
    try:
        assert backend.calls == ["acquire", "release", "acquire"]
        assert backend.held
    finally:
        controller.stop()

    assert not backend.held


def test_release_happens_once_per_hold_under_churn() -> None:
    backend = FakeBackend()
    controller = HoldController(backend=backend)

    for _ in range(10):
        controller.start(TimerTrigger(30))
    controller.stop()

    assert backend.calls.count("acquire") == 10
    assert backend.calls.count("release") == 10
    assert not backend.held


def test_on_change_fires_for_start_stop_and_expiry() -> None:
    seen = threading.Semaphore(0)
    controller = HoldController(backend=FakeBackend(), on_change=seen.release)

    controller.start(IndefiniteTrigger())
    assert seen.acquire(timeout=5)

    controller.stop()
    assert seen.acquire(timeout=5)

    controller.start(TimerTrigger(0.2))
    assert seen.acquire(timeout=5)
    # And again when the timer runs out on its own.
    assert seen.acquire(timeout=5)


def test_a_failing_backend_leaves_the_controller_idle() -> None:
    class Refusing(FakeBackend):
        def acquire(self, wants: Wants, reason: str) -> None:
            raise RuntimeError("nope")

    controller = HoldController(backend=Refusing())

    with pytest.raises(RuntimeError):
        controller.start(IndefiniteTrigger())

    assert not controller.status().active
