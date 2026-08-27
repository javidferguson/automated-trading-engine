"""Bar-size parsing used by the replay and delayed sources."""

import pytest

from trading_engine.bars.replay import parse_bar_size_seconds


@pytest.mark.parametrize(
    "text,expected",
    [
        ("5 secs", 5),
        ("30 secs", 30),
        ("1 min", 60),
        ("5 mins", 300),
        ("1 hour", 3600),
        ("  15   mins ", 900),
        ("1 second", 1),
    ],
)
def test_parse_bar_size_seconds(text, expected):
    assert parse_bar_size_seconds(text) == expected


@pytest.mark.parametrize("text", ["", "5", "banana", "5 fortnights", "1 day"])
def test_parse_bar_size_rejects_nonsense(text):
    with pytest.raises(ValueError):
        parse_bar_size_seconds(text)
