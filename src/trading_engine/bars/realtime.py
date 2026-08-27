"""DATA_MODE=realtime -- live 5-second bars from ib.reqRealTimeBars.

Requires a paid IB market-data subscription. There is no delayed equivalent of
reqRealTimeBars, which is why the ``delayed`` mode polls historical bars instead.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from ib_async import IB, Contract, RealTimeBarList

from ..models import Bar

logger = logging.getLogger(__name__)

IB_REALTIME_BAR_SECONDS = 5  # IB only supports 5-second real-time bars


class RealTimeBarSource:
    """Bridges ib_async's RealTimeBarList update event onto an async queue."""

    source_bar_seconds = IB_REALTIME_BAR_SECONDS

    def __init__(self, ib: IB, contract: Contract, use_rth: bool = True):
        self.ib = ib
        self.contract = contract
        self.use_rth = use_rth
        self._queue: asyncio.Queue[Bar] = asyncio.Queue()
        self._subscription: Optional[RealTimeBarList] = None

    def _on_update(self, bars: RealTimeBarList, has_new_bar: bool) -> None:
        if not has_new_bar or not bars:
            return
        rt = bars[-1]
        self._queue.put_nowait(
            Bar(
                timestamp=rt.time,
                open=rt.open_,
                high=rt.high,
                low=rt.low,
                close=rt.close,
                volume=int(rt.volume) if rt.volume and rt.volume > 0 else 0,
            )
        )

    async def stream(self) -> AsyncIterator[Bar]:
        logger.info(
            "Subscribing to %ds real-time bars for %s", self.source_bar_seconds, self.contract.symbol
        )
        self._subscription = self.ib.reqRealTimeBars(
            self.contract, self.source_bar_seconds, "TRADES", self.use_rth
        )
        self._subscription.updateEvent += self._on_update

        try:
            while True:
                yield await self._queue.get()
        finally:
            await self.close()

    async def close(self) -> None:
        if self._subscription is not None:
            self._subscription.updateEvent -= self._on_update
            self.ib.cancelRealTimeBars(self._subscription)
            self._subscription = None
            logger.info("Cancelled real-time bar subscription")
