"""Core data models for the ORB + GEX trading engine.

Ported from Bot_ORB_Gamma/models/data_models.py (branch jf/test-ca-code) with
additions for the data-source mode and the trade decision.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DataMode(str, Enum):
    """Where price bars come from.

    Deliberately independent of paper/live account selection. ``TRADING_MODE``
    picks the *account*; this picks the *data source*. Conflating them is how a
    test run ends up pointed at the wrong account.
    """

    REALTIME = "realtime"
    DELAYED = "delayed"
    REPLAY = "replay"

    @property
    def can_trade(self) -> bool:
        """Replay prices are historical, so an order derived from them is
        meaningless. Enforced in OrderManager, not just at the call site."""
        return self is not DataMode.REPLAY

    @property
    def market_data_type(self) -> int:
        """IB market data type: 1 = live, 3 = delayed."""
        return 1 if self is DataMode.REALTIME else 3


class Bar(BaseModel):
    """A single OHLCV price bar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Signal(BaseModel):
    """A trading signal produced by a strategy."""

    timestamp: datetime
    symbol: str
    signal_type: SignalType
    strategy: str
    price: Optional[float] = None


class OptionRight(str, Enum):
    CALL = "C"
    PUT = "P"


class GEXResult(BaseModel):
    """Output of the gamma-exposure scan."""

    expiration: str  # YYYYMMDD
    highest_gex_strike: float
    highest_gex_value: float
    gex_by_strike: dict[float, float] = Field(default_factory=dict)
    strikes_analyzed: int = 0
    strikes_with_data: int = 0

    as_of: Optional[date] = None
    """The session this scan was meant to represent."""

    point_in_time: bool = True
    """False when the expiration we wanted was unavailable and a later one was
    substituted. Only ever False in replay: IB drops expired contracts from the
    chain, so historical option greeks and open interest cannot be retrieved.
    A GEX result with this False describes *today's* positioning, not the
    session being replayed, and must not be treated as a backtest input."""


class TradeDecision(BaseModel):
    """The concrete trade the engine proposes, before sizing and confirmation."""

    symbol: str
    right: OptionRight
    strike: float
    expiration: str
    quantity: int
    entry_price: float
    take_profit_price: float
    stop_loss_price: float
    signal: Signal
    spot_price: float
    highest_gex_strike: float

    @property
    def total_debit(self) -> float:
        """What this costs if the entry fills at the limit."""
        return self.entry_price * self.quantity * 100
