"""Bar sources: where the breakout stage gets its price bars.

The engine consumes an async stream of :class:`~trading_engine.models.Bar` and
does not care where it came from. That indirection is what makes the strategy
testable without a market-data subscription or an open market.

Selection is by ``DATA_MODE`` (env) / ``data.mode`` (YAML):

    realtime : live 5-second bars      -- needs a paid IB subscription
    delayed  : polled historical bars  -- no subscription, ~15 min behind
    replay   : a past session re-fed   -- no subscription, cannot trade
"""

from __future__ import annotations

import logging
from datetime import date as date_cls, datetime, time
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from ib_async import IB, Contract

from ..config import EngineConfig
from ..models import Bar, DataMode

logger = logging.getLogger(__name__)


def bar_from_ib(raw: Any) -> Bar:
    """Convert an ib_async BarData/RealTimeBar into our Bar model.

    IB uses `.date` on historical bars, `.time`/`.open_` on real-time ones, and
    returns a plain `date` for daily bars. The strategies work on `.timestamp`,
    so every entry point has to come through here.
    """
    timestamp = getattr(raw, "date", None)
    if timestamp is None:
        timestamp = raw.time
    if isinstance(timestamp, date_cls) and not isinstance(timestamp, datetime):
        timestamp = datetime.combine(timestamp, time())

    volume = getattr(raw, "volume", 0)

    return Bar(
        timestamp=timestamp,
        open=getattr(raw, "open", None) if hasattr(raw, "open") else raw.open_,
        high=raw.high,
        low=raw.low,
        close=raw.close,
        volume=int(volume) if volume and volume > 0 else 0,
    )


@runtime_checkable
class BarSource(Protocol):
    """An async stream of price bars."""

    source_bar_seconds: int
    """Nominal duration of one emitted bar. The aggregator needs this to know
    when a candle's window is covered."""

    def stream(self) -> AsyncIterator[Bar]:
        """Yield bars until the source is exhausted or cancelled."""
        ...

    async def close(self) -> None:
        """Release any broker subscriptions."""
        ...


def make_bar_source(ib: IB, contract: Contract, config: EngineConfig) -> BarSource:
    """Build the bar source named by the resolved DATA_MODE."""
    # Imported here so a mode's dependencies are only touched when it is used.
    from .delayed import DelayedBarSource
    from .realtime import RealTimeBarSource
    from .replay import ReplayBarSource

    mode = config.data_mode

    if mode is DataMode.REALTIME:
        return RealTimeBarSource(ib, contract)
    if mode is DataMode.DELAYED:
        return DelayedBarSource(
            ib,
            contract,
            bar_size=config.data.delayed.bar_size,
            lookback=config.data.delayed.lookback,
            poll_seconds=config.data.delayed.poll_seconds,
        )
    if mode is DataMode.REPLAY:
        if config.data.replay.date is None:
            raise ValueError(
                "DATA_MODE=replay requires data.replay_date in the config "
                "(or REPLAY_DATE in the environment)."
            )
        return ReplayBarSource(
            ib,
            contract,
            replay_date=config.data.replay.date,
            bar_size=config.data.replay.bar_size,
            speed=config.data.replay.speed,
            exchange_tz=config.opening_range.exchange_timezone,
        )

    raise ValueError(f"Unknown data mode: {mode}")
