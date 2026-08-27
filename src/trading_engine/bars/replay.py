"""DATA_MODE=replay -- a past session fed through as if it were live.

This is the correctness gate for the whole strategy: it needs no market-data
subscription and no open market, so the state machine can be exercised end to
end at any time. Orders are blocked in this mode (see OrderManager) because the
prices are historical.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from typing import AsyncIterator

from ib_async import IB, Contract

from ..models import Bar
from .base import bar_from_ib

logger = logging.getLogger(__name__)

# IB bar-size strings, e.g. "30 secs", "1 min", "5 mins"
_BAR_SIZE_RE = re.compile(r"^\s*(\d+)\s+(sec|secs|second|seconds|min|mins|minute|minutes|hour|hours)\s*$", re.I)
_UNIT_SECONDS = {"sec": 1, "min": 60, "hour": 3600}


def parse_bar_size_seconds(bar_size: str) -> int:
    """Convert an IB bar-size string such as '30 secs' into seconds."""
    match = _BAR_SIZE_RE.match(bar_size)
    if not match:
        raise ValueError(f"Unrecognised bar size: {bar_size!r}")
    value, unit = int(match.group(1)), match.group(2).lower()
    for prefix, seconds in _UNIT_SECONDS.items():
        if unit.startswith(prefix):
            return value * seconds
    raise ValueError(f"Unrecognised bar size unit: {bar_size!r}")


class ReplayBarSource:
    """Fetches one historical RTH session and yields its bars in order."""

    def __init__(
        self,
        ib: IB,
        contract: Contract,
        replay_date: date,
        bar_size: str = "30 secs",
        speed: float = 0.0,
        session_end: time = time(16, 0),
        exchange_tz: str = "America/New_York",
    ):
        self.ib = ib
        self.contract = contract
        self.replay_date = replay_date
        self.bar_size = bar_size
        self.speed = speed
        self.session_end = session_end
        self.exchange_tz = ZoneInfo(exchange_tz)
        self.source_bar_seconds = parse_bar_size_seconds(bar_size)

    async def stream(self) -> AsyncIterator[Bar]:
        # Aware, for the same reason as the opening-range request: a naive
        # endDateTime is resolved by IB in an unpredictable zone.
        end_dt = datetime.combine(self.replay_date, self.session_end, tzinfo=self.exchange_tz)
        logger.info(
            "Replaying %s session for %s using %s bars",
            self.replay_date,
            self.contract.symbol,
            self.bar_size,
        )

        bars = await self.ib.reqHistoricalDataAsync(
            self.contract,
            endDateTime=end_dt,
            durationStr="1 D",
            barSizeSetting=self.bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )

        if not bars:
            logger.error(
                "No historical bars returned for %s on %s. Is that a trading day, "
                "and does the contract resolve?",
                self.contract.symbol,
                self.replay_date,
            )
            return

        logger.info("Replaying %d bars", len(bars))

        for raw in bars:
            yield bar_from_ib(raw)

            if self.speed > 0:
                await asyncio.sleep(self.speed)

        logger.info("Replay complete")

    async def close(self) -> None:
        """Nothing to release: the historical request already completed."""
        return None
