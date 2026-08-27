"""Opening range tests.

Ported from Bot_ORB_Gamma/tests/strategy/test_opening_range.py.

The original fixture built bars with ``datetime.now()``, which only falls inside
the 09:30-10:00 window if you happen to run the suite during that half hour --
outside it, ``add_bar`` rejected every bar and the assertions failed. These use
explicit in-window timestamps instead, and the window boundaries now have
dedicated coverage.
"""

from datetime import datetime, time

import pytest

from trading_engine.models import Bar
from trading_engine.strategy.opening_range import OpeningRangeStrategy

SESSION = datetime(2026, 8, 26)


def bar_at(hour, minute, high, low, open_=100.0, close=100.0):
    return Bar(
        timestamp=SESSION.replace(hour=hour, minute=minute),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


@pytest.fixture
def orb():
    return OpeningRangeStrategy.from_config(
        {"opening_range": {"market_open_time": "09:30:00", "duration_minutes": 30}}
    )


def test_from_config_parses_open_time_and_duration(orb):
    assert orb.market_open == time(9, 30)
    assert orb.duration_minutes == 30


def test_calculate_levels(orb):
    """High is the max of highs, low is the min of lows."""
    for b in [
        bar_at(9, 30, high=105, low=99),
        bar_at(9, 45, high=110, low=101),
        bar_at(9, 59, high=109, low=98),
    ]:
        assert orb.add_bar(b) is True

    high, low = orb.calculate_levels()

    assert high == 110
    assert low == 98
    assert orb.is_complete is True


def test_calculate_levels_no_bars(orb):
    high, low = orb.calculate_levels()
    assert high is None
    assert low is None
    assert orb.is_complete is False


def test_bar_at_market_open_is_included(orb):
    """The window is half-open: 09:30 is in."""
    assert orb.add_bar(bar_at(9, 30, high=101, low=99)) is True


def test_bar_at_window_end_is_excluded(orb):
    """10:00 is the first bar of the next period, not the last of this one."""
    assert orb.add_bar(bar_at(10, 0, high=101, low=99)) is False
    assert orb.bars == []


def test_premarket_bar_is_excluded(orb):
    assert orb.add_bar(bar_at(9, 15, high=120, low=80)) is False


def test_out_of_window_bars_do_not_affect_levels(orb):
    """A wide pre-market bar must not widen the range."""
    orb.add_bar(bar_at(9, 15, high=999, low=1))
    orb.add_bar(bar_at(9, 40, high=105, low=99))
    high, low = orb.calculate_levels()
    assert (high, low) == (105, 99)
