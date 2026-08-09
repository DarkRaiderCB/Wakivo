from __future__ import annotations

import pytest

from wakivo.triggers import format_duration, parse_duration


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("45", 45),
        ("90s", 90),
        ("20m", 1200),
        ("2h", 7200),
        ("1d", 86400),
        ("1h30m", 5400),
        ("1h30m15s", 5415),
        ("1.5h", 5400),
        ("  2H  ", 7200),
    ],
)
def test_parses_supported_forms(text: str, seconds: float) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "5x",
        "abc",
        "-5",
        "1h2x",
        "h",
        "1 h",
    ],
)
def test_rejects_malformed_input(text: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(text)


@pytest.mark.parametrize("text", ["0", "0s", "0h0m"])
def test_rejects_zero(text: str) -> None:
    # A zero-length hold would acquire and immediately release, which is
    # almost certainly a typo rather than an intent.
    with pytest.raises(ValueError):
        parse_duration(text)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0s"),
        (45, "45s"),
        (90, "1m30s"),
        (600, "10m00s"),
        (3661, "1h01m01s"),
        (45.4, "45s"),
        (45.6, "46s"),
    ],
)
def test_formats_for_humans(seconds: float, text: str) -> None:
    assert format_duration(seconds) == text
