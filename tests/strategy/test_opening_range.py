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


# ------------------------------------------------------- timezone handling
#
# Regression cover for a bug the fake-IB engine test could not catch: it
# returned naive 09:30 timestamps, i.e. the already-correct case. In reality the
# Gateway image defaults to Etc/UTC, so IB stamps a 09:30 ET bar as 13:30 and
# every bar fell outside the window -- an empty range and a silent shutdown.

from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")


def aware_bar(dt, high=101.0, low=99.0):
    return Bar(timestamp=dt, open=100.0, high=high, low=low, close=100.0, volume=1000)


def test_utc_aware_bars_are_converted_to_exchange_time(orb):
    """13:30 UTC is 09:30 ET in August, so it belongs in the opening range."""
    assert orb.add_bar(aware_bar(datetime(2026, 8, 26, 13, 30, tzinfo=UTC))) is True


def test_utc_aware_bars_outside_the_window_are_still_rejected(orb):
    """14:00 UTC is 10:00 ET -- the first bar after the range."""
    assert orb.add_bar(aware_bar(datetime(2026, 8, 26, 14, 0, tzinfo=UTC))) is False


def test_levels_are_correct_from_utc_aware_bars(orb):
    for dt, hi, lo in [
        (datetime(2026, 8, 26, 13, 30, tzinfo=UTC), 105, 99),
        (datetime(2026, 8, 26, 13, 45, tzinfo=UTC), 110, 101),
        (datetime(2026, 8, 26, 13, 59, tzinfo=UTC), 109, 98),
    ]:
        orb.add_bar(aware_bar(dt, high=hi, low=lo))
    assert orb.calculate_levels() == (110, 98)


def test_exchange_aware_bars_work_too(orb):
    assert orb.add_bar(aware_bar(datetime(2026, 8, 26, 9, 30, tzinfo=ET))) is True


def test_naive_bars_are_treated_as_exchange_local(orb):
    """What TIME_ZONE on the Gateway container guarantees."""
    assert orb.add_bar(aware_bar(datetime(2026, 8, 26, 9, 30))) is True


def test_dst_boundary_is_handled(orb):
    """In January, 09:30 ET is 14:30 UTC rather than 13:30."""
    assert orb.add_bar(aware_bar(datetime(2026, 1, 15, 14, 30, tzinfo=UTC))) is True
    assert orb.add_bar(aware_bar(datetime(2026, 1, 15, 13, 30, tzinfo=UTC))) is False


def test_rejected_count_tracks_out_of_window_bars(orb):
    """Feeds the timezone-mismatch diagnostic in calculate_levels()."""
    for hour in (13, 14, 15):
        orb.add_bar(aware_bar(datetime(2026, 8, 26, hour, 0)))  # naive, so UTC-looking
    assert orb.rejected == 3
    assert orb.calculate_levels() == (None, None)
