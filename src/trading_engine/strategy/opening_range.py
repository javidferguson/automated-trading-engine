"""Stage 1: Opening Range Identification.

Defines the price range established during the first N minutes of the session.

Ported near-verbatim from Bot_ORB_Gamma/strategy/opening_range.py. The original
used a ``BarLike`` Protocol rather than importing broker types, which is why it
carries over unchanged -- there is no IB dependency in here at all.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any, Optional, Protocol
from zoneinfo import ZoneInfo

DEFAULT_EXCHANGE_TZ = "America/New_York"


class BarLike(Protocol):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


logger = logging.getLogger(__name__)


class OpeningRangeStrategy:
    """Collects bars inside the opening window and derives HIGH/LOW levels."""

    def __init__(
        self,
        market_open: time = time(9, 30),
        duration_minutes: int = 30,
        exchange_tz: str = DEFAULT_EXCHANGE_TZ,
    ):
        self.market_open = market_open
        self.duration_minutes = duration_minutes
        self.exchange_tz = ZoneInfo(exchange_tz)

        self.bars: list[BarLike] = []
        self.high_level: Optional[float] = None
        self.low_level: Optional[float] = None
        self.is_complete: bool = False
        self.rejected: int = 0

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "OpeningRangeStrategy":
        orb_cfg = config.get("opening_range", {})
        mo_str = orb_cfg.get("market_open_time", "09:30:00")
        market_open = datetime.strptime(mo_str, "%H:%M:%S").time()
        duration = orb_cfg.get("duration_minutes", 30)
        tz = orb_cfg.get("exchange_timezone", DEFAULT_EXCHANGE_TZ)
        return cls(market_open=market_open, duration_minutes=duration, exchange_tz=tz)

    def add_bar(self, bar: BarLike) -> bool:
        """Add a bar if it falls inside the opening window. Returns whether it was kept."""
        if self.is_bar_valid(bar):
            self.bars.append(bar)
            logger.debug("ORB: bar added %s | H:%s L:%s", bar.timestamp, bar.high, bar.low)
            return True

        self.rejected += 1
        logger.debug("ORB: bar ignored (outside window) %s", bar.timestamp)
        return False

    def to_exchange_time(self, ts: datetime) -> datetime:
        """Express a bar timestamp as naive exchange-local time.

        An aware timestamp is converted. A naive one is assumed to already be
        exchange-local, which is only true if the Gateway's TimeZone is set to
        the exchange's -- hence TIME_ZONE in docker-compose. With the image
        default of Etc/UTC, a 09:30 ET bar arrives as a naive 13:30 and silently
        falls outside the window.
        """
        if ts.tzinfo is not None:
            return ts.astimezone(self.exchange_tz).replace(tzinfo=None)
        return ts

    def is_bar_valid(self, bar: BarLike) -> bool:
        """True when the bar starts within [session_open, session_open + duration).

        Half-open on purpose: with a 09:30 open and a 30-minute range, 09:59 is
        inside and 10:00 is not.
        """
        bar_dt = self.to_exchange_time(bar.timestamp)
        session_open = datetime.combine(bar_dt.date(), self.market_open)
        session_end = session_open + timedelta(minutes=self.duration_minutes)
        return session_open <= bar_dt < session_end

    def calculate_levels(self) -> tuple[Optional[float], Optional[float]]:
        """Return (HIGH_LEVEL, LOW_LEVEL) from the collected bars."""
        if not self.bars:
            if self.rejected:
                # Overwhelmingly the cause: the Gateway is on Etc/UTC, so the
                # bars are real but their timestamps are not exchange-local.
                logger.error(
                    "ORB: all %d bars fell outside the %s-%s window. The usual cause is "
                    "a timezone mismatch -- check TIME_ZONE in docker-compose is set to "
                    "the exchange timezone (%s), not the image default of Etc/UTC.",
                    self.rejected,
                    self.market_open,
                    (datetime.combine(datetime.today(), self.market_open)
                     + timedelta(minutes=self.duration_minutes)).time(),
                    self.exchange_tz.key,
                )
            else:
                logger.warning("ORB: no bars collected, cannot calculate levels")
            return None, None

        self.high_level = max(b.high for b in self.bars)
        self.low_level = min(b.low for b in self.bars)
        self.is_complete = True

        logger.info(
            "ORB: range calculated | high=%.2f low=%.2f (%d bars)",
            self.high_level,
            self.low_level,
            len(self.bars),
        )
        return self.high_level, self.low_level
