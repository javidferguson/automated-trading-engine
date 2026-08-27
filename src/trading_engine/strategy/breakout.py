"""Stage 2: Breakout Detection.

Aggregates small source bars (typically 5-second) into candles (typically
5-minute) and tests each completed candle for a clean-body break of the opening
range.

Breakout rule, unchanged from the original design:

    Bullish : close > open  AND  low  > HIGH_LEVEL   (whole body above the range)
    Bearish : close < open  AND  high < LOW_LEVEL    (whole body below the range)

Ported from Bot_ORB_Gamma/strategy/breakout.py, with one deliberate change to
the aggregator -- see ``_window_start``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Protocol

from ..models import Bar, Signal, SignalType


class BarLike(Protocol):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


logger = logging.getLogger(__name__)

STRATEGY_NAME = "BreakoutStrategy"


class BreakoutStrategy:
    """Stateful aggregator + breakout detector.

    The original implementation flushed a candle after counting a fixed number
    of source bars (``aggregation_seconds // 5``). That silently misaligns the
    moment a source bar is missing, which is routine on a real feed -- IB emits
    no 5-second bar for an interval with no trades, so a thin instrument would
    drift a candle boundary further out of alignment all session.

    This version anchors each candle to a wall-clock boundary instead, and
    flushes when the window is covered or when a bar arrives belonging to a
    later window. Missing bars shorten a candle rather than shifting every
    subsequent one.
    """

    def __init__(self, aggregation_seconds: int, symbol: str, source_bar_seconds: int = 5):
        if aggregation_seconds <= 0 or source_bar_seconds <= 0:
            raise ValueError("Bar sizes must be positive.")
        if aggregation_seconds % source_bar_seconds != 0:
            raise ValueError(
                f"aggregation_seconds ({aggregation_seconds}) must be a multiple of "
                f"source_bar_seconds ({source_bar_seconds})."
            )

        self.aggregation_seconds = aggregation_seconds
        self.source_bar_seconds = source_bar_seconds
        self.bars_to_aggregate = aggregation_seconds // source_bar_seconds
        self.symbol = symbol

        self._pending: list[BarLike] = []
        self._window_start_ts: Optional[datetime] = None

        logger.info(
            "Breakout strategy for %s: aggregating %ds bars into %ds candles",
            symbol,
            source_bar_seconds,
            aggregation_seconds,
        )

    @classmethod
    def from_config(cls, config: dict[str, Any], symbol: str) -> "BreakoutStrategy":
        breakout_cfg = config.get("breakout", {})
        agg_seconds = breakout_cfg.get("bar_size_seconds", 300)
        return cls(aggregation_seconds=agg_seconds, symbol=symbol)

    # ------------------------------------------------------------------ #
    # Aggregation
    # ------------------------------------------------------------------ #

    def _window_start(self, ts: datetime) -> datetime:
        """Floor a timestamp to its aggregation boundary (wall-clock aligned)."""
        midnight = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = int((ts - midnight).total_seconds())
        floored = (elapsed // self.aggregation_seconds) * self.aggregation_seconds
        return midnight + timedelta(seconds=floored)

    def _hold(self, ts: datetime) -> Signal:
        return Signal(
            timestamp=ts,
            symbol=self.symbol,
            signal_type=SignalType.HOLD,
            strategy=STRATEGY_NAME,
        )

    def _aggregate(self) -> Optional[Bar]:
        """Collapse the pending source bars into a single candle."""
        if not self._pending:
            return None

        candle = Bar(
            timestamp=self._window_start_ts or self._pending[0].timestamp,
            open=self._pending[0].open,
            high=max(b.high for b in self._pending),
            low=min(b.low for b in self._pending),
            close=self._pending[-1].close,
            volume=sum(b.volume for b in self._pending),
        )
        logger.debug(
            "Aggregated candle %s O:%s H:%s L:%s C:%s (%d/%d source bars)",
            candle.timestamp,
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            len(self._pending),
            self.bars_to_aggregate,
        )
        return candle

    def _flush(self, high_level: float, low_level: float) -> Signal:
        """Emit the pending candle and test it for a breakout."""
        candle = self._aggregate()
        ts = candle.timestamp if candle else datetime.now()
        self._pending = []
        self._window_start_ts = None

        if candle is None:
            return self._hold(ts)
        return self.check_breakout(candle, high_level, low_level)

    def add_realtime_bar(self, bar: BarLike, high_level: float, low_level: float) -> Signal:
        """Feed one source bar. Returns a signal when a candle completes, else HOLD."""
        window_start = self._window_start(bar.timestamp)
        signal: Optional[Signal] = None

        if self._window_start_ts is not None and window_start != self._window_start_ts:
            if window_start < self._window_start_ts:
                logger.warning(
                    "Out-of-order bar %s is older than the current window %s; ignoring.",
                    bar.timestamp,
                    self._window_start_ts,
                )
                return self._hold(bar.timestamp)
            # A bar from a later window arrived: the previous candle is done.
            signal = self._flush(high_level, low_level)

        if self._window_start_ts is None:
            self._window_start_ts = window_start

        self._pending.append(bar)

        # Flush as soon as this bar covers the end of the window, so a candle is
        # emitted the moment it completes rather than when the next one starts.
        window_end = self._window_start_ts + timedelta(seconds=self.aggregation_seconds)
        if bar.timestamp + timedelta(seconds=self.source_bar_seconds) >= window_end:
            completed = self._flush(high_level, low_level)
            if completed.signal_type is not SignalType.HOLD:
                return completed
            signal = signal or completed

        return signal or self._hold(bar.timestamp)

    def flush_pending(self, high_level: float, low_level: float) -> Signal:
        """Force-close a partial candle (end of session, or end of a replay)."""
        if not self._pending:
            return self._hold(datetime.now())
        return self._flush(high_level, low_level)

    # ------------------------------------------------------------------ #
    # Breakout test
    # ------------------------------------------------------------------ #

    def check_breakout(self, bar: BarLike, high_level: float, low_level: float) -> Signal:
        """Apply the clean-body breakout rule to a completed candle."""
        if bar is None or high_level is None or low_level is None:
            logger.warning("check_breakout called with invalid inputs")
            return self._hold(datetime.now())

        logger.debug(
            "Checking candle %s O:%s H:%s L:%s C:%s against range %.2f-%.2f",
            bar.timestamp,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            low_level,
            high_level,
        )

        if bar.close > bar.open and bar.low > high_level:
            logger.info(
                "BULLISH breakout at %s (close %.2f, body low %.2f > ORB high %.2f)",
                bar.timestamp,
                bar.close,
                bar.low,
                high_level,
            )
            return Signal(
                timestamp=bar.timestamp,
                symbol=self.symbol,
                signal_type=SignalType.BUY,
                strategy=STRATEGY_NAME,
                price=bar.close,
            )

        if bar.close < bar.open and bar.high < low_level:
            logger.info(
                "BEARISH breakout at %s (close %.2f, body high %.2f < ORB low %.2f)",
                bar.timestamp,
                bar.close,
                bar.high,
                low_level,
            )
            return Signal(
                timestamp=bar.timestamp,
                symbol=self.symbol,
                signal_type=SignalType.SELL,
                strategy=STRATEGY_NAME,
                price=bar.close,
            )

        return self._hold(bar.timestamp)
