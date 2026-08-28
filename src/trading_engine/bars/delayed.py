"""DATA_MODE=delayed -- polled historical bars, no subscription required.

``reqRealTimeBars`` needs live market data, so delayed mode cannot use it. This
source instead re-requests a short window of recent historical bars on a timer
and emits the ones it has not seen before. Historical data is available without
a market-data subscription, at roughly a 15-minute lag.

That lag is the whole story here: a 0DTE opening-range breakout cannot be traded
on 15-minute-old bars, because the move is over by the time the bar arrives. Use
this mode to watch the state machine run against live-shaped data -- not to trade.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import AsyncIterator, Optional

from ib_async import IB, Contract

from ..models import Bar
from .base import bar_from_ib
from .replay import parse_bar_size_seconds

logger = logging.getLogger(__name__)


class DelayedBarSource:
    """Polls recent historical bars and emits newly-seen ones in order."""

    def __init__(
        self,
        ib: IB,
        contract: Contract,
        bar_size: str = "30 secs",
        lookback: str = "1800 S",
        poll_seconds: float = 30.0,
    ):
        self.ib = ib
        self.contract = contract
        self.bar_size = bar_size
        self.lookback = lookback
        self.poll_seconds = poll_seconds
        self.source_bar_seconds = parse_bar_size_seconds(bar_size)
        self._last_emitted: Optional[datetime] = None
        self._closed = False

    async def _poll_once(self) -> list[Bar]:
        bars = await self.ib.reqHistoricalDataAsync(
            self.contract,
            endDateTime="",  # now
            durationStr=self.lookback,
            barSizeSetting=self.bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )

        fresh: list[Bar] = []
        for raw in bars or []:
            bar = bar_from_ib(raw)
            if self._last_emitted is not None and bar.timestamp <= self._last_emitted:
                continue
            fresh.append(bar)
        return fresh

    async def stream(self) -> AsyncIterator[Bar]:
        logger.warning(
            "DATA_MODE=delayed: bars lag the market by roughly 15 minutes, so any "
            "entry limit is priced off stale data. Orders ARE permitted in this "
            "mode and you will be asked to confirm -- treat a fill as a test of "
            "the mechanism, not of the strategy."
        )

        while not self._closed:
            try:
                fresh = await self._poll_once()
            except Exception:
                logger.exception("Delayed bar poll failed; retrying next interval")
                fresh = []

            for bar in fresh:
                self._last_emitted = bar.timestamp
                yield bar

            await asyncio.sleep(self.poll_seconds)

    async def close(self) -> None:
        self._closed = True
