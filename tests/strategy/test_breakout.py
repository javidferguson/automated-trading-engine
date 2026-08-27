"""Breakout detection tests.

Ported from Bot_ORB_Gamma/tests/strategy/test_breakout.py, plus cases covering
the boundary-aligned aggregator that replaced the original count-based one.
"""

from datetime import datetime, timedelta

import pytest

from trading_engine.models import SignalType
from trading_engine.strategy.breakout import BreakoutStrategy

ORB_HIGH = 4000.0
ORB_LOW = 3990.0


class MockBar:
    def __init__(self, timestamp, o, h, l, c, v=10):
        self.timestamp = timestamp
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v

    def __repr__(self):
        return f"Bar(T={self.timestamp.time()}, O={self.open}, H={self.high}, L={self.low}, C={self.close})"


@pytest.fixture
def strategy():
    """1-minute candles built from 5-second bars."""
    return BreakoutStrategy.from_config({"breakout": {"bar_size_seconds": 60}}, symbol="TEST")


@pytest.fixture
def window_start():
    """A clean minute boundary, so a 60-second window starts exactly here."""
    return datetime(2026, 8, 26, 10, 0, 0)


def _feed(strategy, start, builder, count=12):
    signal = None
    for i in range(count):
        bar = builder(i, start + timedelta(seconds=i * 5))
        signal = strategy.add_realtime_bar(bar, ORB_HIGH, ORB_LOW)
    return signal


def test_bullish_breakout(strategy, window_start):
    """A rising candle whose entire body sits above the ORB high is BULLISH."""
    signal = _feed(
        strategy,
        window_start,
        lambda i, ts: MockBar(ts, 4001 + i * 0.2, 4001.5 + i * 0.2, 4000.5 + i * 0.2, 4001.2 + i * 0.2),
    )
    assert signal.signal_type == SignalType.BUY
    assert signal.price == pytest.approx(4001.2 + 11 * 0.2)


def test_bearish_breakout(strategy, window_start):
    """A falling candle whose entire body sits below the ORB low is BEARISH."""
    signal = _feed(
        strategy,
        window_start,
        lambda i, ts: MockBar(ts, 3989 - i * 0.2, 3989.5 - i * 0.2, 3988.5 - i * 0.2, 3988.8 - i * 0.2),
    )
    assert signal.signal_type == SignalType.SELL


def test_no_breakout_inside_range(strategy, window_start):
    """A candle formed entirely inside the range produces no signal."""
    signal = _feed(strategy, window_start, lambda i, ts: MockBar(ts, 3995, 3996, 3994, 3995.5))
    assert signal.signal_type == SignalType.HOLD


def test_wick_above_range_is_not_a_breakout(strategy, window_start):
    """The break must be clean: a body straddling the level does not count."""
    # High pokes above ORB_HIGH but the low stays inside the range.
    signal = _feed(strategy, window_start, lambda i, ts: MockBar(ts, 3998, 4002, 3997, 3999))
    assert signal.signal_type == SignalType.HOLD


def test_bullish_body_above_range_but_bearish_candle_is_not_a_breakout(strategy, window_start):
    """Direction matters: a down candle above the range is not a bullish break."""
    signal = _feed(
        strategy,
        window_start,
        lambda i, ts: MockBar(ts, 4010 - i * 0.2, 4011, 4005, 4006 - i * 0.2),
    )
    assert signal.signal_type == SignalType.HOLD


def test_no_signal_before_candle_completes(strategy, window_start):
    """Partial candles emit HOLD, not an early signal."""
    signal = _feed(
        strategy,
        window_start,
        lambda i, ts: MockBar(ts, 4001 + i * 0.2, 4001.5 + i * 0.2, 4000.5 + i * 0.2, 4001.2 + i * 0.2),
        count=11,
    )
    assert signal.signal_type == SignalType.HOLD


def test_missing_source_bars_do_not_shift_the_window(strategy, window_start):
    """A gap in the feed shortens the candle instead of misaligning later ones.

    The original count-based aggregator would wait for a 12th bar that never
    arrives and drift every subsequent candle boundary.
    """
    # Only 8 of the 12 possible 5-second slots produce a bar.
    signal = None
    for i in (0, 1, 2, 5, 6, 8, 9, 11):
        ts = window_start + timedelta(seconds=i * 5)
        signal = strategy.add_realtime_bar(
            MockBar(ts, 4001 + i * 0.2, 4001.5 + i * 0.2, 4000.5 + i * 0.2, 4001.2 + i * 0.2),
            ORB_HIGH,
            ORB_LOW,
        )
    assert signal.signal_type == SignalType.BUY


def test_candle_flushes_when_a_later_window_arrives(strategy, window_start):
    """A bar from the next window closes the previous candle."""
    # Nine bars only -- not enough to reach the window end on their own.
    for i in range(9):
        ts = window_start + timedelta(seconds=i * 5)
        strategy.add_realtime_bar(
            MockBar(ts, 4001 + i * 0.2, 4001.5 + i * 0.2, 4000.5 + i * 0.2, 4001.2 + i * 0.2),
            ORB_HIGH,
            ORB_LOW,
        )
    # First bar of the following minute.
    signal = strategy.add_realtime_bar(
        MockBar(window_start + timedelta(seconds=60), 4010, 4011, 4009, 4010.5),
        ORB_HIGH,
        ORB_LOW,
    )
    assert signal.signal_type == SignalType.BUY


def test_out_of_order_bar_is_ignored(strategy, window_start):
    """A bar older than the open window is dropped, not folded in."""
    strategy.add_realtime_bar(MockBar(window_start + timedelta(seconds=60), 4010, 4011, 4009, 4010.5), ORB_HIGH, ORB_LOW)
    signal = strategy.add_realtime_bar(MockBar(window_start, 3995, 3996, 3994, 3995), ORB_HIGH, ORB_LOW)
    assert signal.signal_type == SignalType.HOLD
    assert len(strategy._pending) == 1


def test_aggregation_must_divide_evenly():
    with pytest.raises(ValueError):
        BreakoutStrategy(aggregation_seconds=7, symbol="TEST", source_bar_seconds=5)
