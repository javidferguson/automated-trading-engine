"""End-to-end state machine walk, driven by a fake IB.

This is the CI version of the replay gate: it proves the engine walks
CONNECTING -> GETTING_OPENING_RANGE -> MONITORING_BREAKOUT -> ANALYZING_GEX ->
PENDING_TRADE_EXECUTION -> SHUTDOWN and reaches the right decision, without
needing a Gateway, a market-data subscription, or an open market.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

import pytest

from trading_engine.config import (
    AccountConfig,
    BreakoutConfig,
    ConnectionConfig,
    DataConfig,
    EngineConfig,
    GEXConfig,
    InstrumentConfig,
    OpeningRangeConfig,
    TradeExecutionConfig,
)
from trading_engine.engine import Engine, State
from trading_engine.execution.confirmation import RejectAllGate
from trading_engine.models import DataMode

SESSION = date(2026, 8, 26)
OPEN = datetime.combine(SESSION, time(9, 30))


# --------------------------------------------------------------- fake broker

@dataclass
class FakeBar:
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 1000


@dataclass
class FakeGreeks:
    gamma: float
    optPrice: float = 3.40


@dataclass
class FakeTicker:
    contract: object
    modelGreeks: Optional[FakeGreeks] = None
    callOpenInterest: float = 0.0
    putOpenInterest: float = 0.0
    bid: float = float("nan")
    ask: float = float("nan")
    last: float = float("nan")


@dataclass
class FakeChain:
    exchange: str = "SMART"
    tradingClass: str = "SPY"
    multiplier: str = "100"
    expirations: list = field(default_factory=lambda: ["20260826", "20260828"])
    strikes: list = field(default_factory=lambda: [float(s) for s in range(445, 456)])


class FakeContract:
    def __init__(self, symbol="SPY", sec_type="STK", exchange="SMART", currency="USD"):
        self.symbol = symbol
        self.secType = sec_type
        self.exchange = exchange
        self.currency = currency
        self.conId = 756733
        self.localSymbol = symbol
        self.strike = 0.0
        self.right = ""


class FakeIB:
    """Enough of ib_async.IB to walk the state machine."""

    def __init__(self, orb_bars, session_bars, accounts=("DU1234567",)):
        self.orb_bars = orb_bars
        self.session_bars = session_bars
        self._accounts = list(accounts)
        self._connected = False
        self.market_data_type = None
        self.cancelled = []
        self.placed = []
        self._hist_calls = 0

    async def connectAsync(self, host, port, clientId):
        self._connected = True

    def isConnected(self):
        return self._connected

    def disconnect(self):
        self._connected = False

    def managedAccounts(self):
        return self._accounts

    def reqMarketDataType(self, kind):
        self.market_data_type = kind

    async def qualifyContractsAsync(self, *contracts):
        for c in contracts:
            if not getattr(c, "conId", 0):
                c.conId = 987654
        return list(contracts)

    async def reqHistoricalDataAsync(self, contract, **kwargs):
        # First call is the opening range; the next is the replay session.
        self._hist_calls += 1
        return self.orb_bars if self._hist_calls == 1 else self.session_bars

    async def reqSecDefOptParamsAsync(self, symbol, fut_exchange, sec_type, con_id):
        return [FakeChain()]

    def reqMktData(self, contract, generic_ticks="", snapshot=False, regulatory=False):
        # Peak gamma at 455 -- above spot, so a bullish break is confirmed.
        gamma = 0.09 if contract.strike == 455.0 else 0.02
        return FakeTicker(
            contract=contract,
            modelGreeks=FakeGreeks(gamma=gamma),
            callOpenInterest=5000 if contract.right == "C" else 0,
            putOpenInterest=1000 if contract.right == "P" else 0,
        )

    def cancelMktData(self, contract):
        self.cancelled.append(contract)

    async def reqTickersAsync(self, *contracts):
        return [FakeTicker(contract=contracts[0], bid=3.30, ask=3.50)]


# ---------------------------------------------------------------- fixtures

def opening_range_bars():
    """Six 5-minute bars establishing a 449-451 range."""
    return [
        FakeBar(OPEN + timedelta(minutes=5 * i), open=450, high=451, low=449, close=450)
        for i in range(6)
    ]


def breakout_session_bars():
    """Post-range bars whose bodies clear 451 cleanly."""
    start = OPEN + timedelta(minutes=30)
    bars = []
    for i in range(12):
        base = 452.0 + i * 0.1
        bars.append(
            FakeBar(start + timedelta(seconds=30 * i), open=base, high=base + 0.3, low=base - 0.1, close=base + 0.2)
        )
    return bars


def make_config(mode=DataMode.REPLAY) -> EngineConfig:
    return EngineConfig(
        connection=ConnectionConfig(host="fake", port=4004, client_id=99),
        account=AccountConfig(type="paper"),
        instrument=InstrumentConfig(ticker="SPY", sec_type="STK", exchange="SMART"),
        opening_range=OpeningRangeConfig(market_open_time="09:30:00", duration_minutes=30, bar_size="5 mins"),
        breakout=BreakoutConfig(bar_size_seconds=300),
        data=DataConfig(mode=mode, replay_date=SESSION, replay_bar_size="30 secs", replay_speed=0),
        gex=GEXConfig(days_to_expiration=0, strikes_quantity=10, data_timeout_seconds=1),
        trade_execution=TradeExecutionConfig(quantity=1),
    )


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # keep journal writes out of the repo
    eng = Engine(make_config(), gate=RejectAllGate())
    eng.ib = FakeIB(opening_range_bars(), breakout_session_bars())
    eng.contract = FakeContract()
    return eng


# ------------------------------------------------------------------- tests

@pytest.mark.asyncio
async def test_full_replay_walk_reaches_a_would_trade_decision(engine):
    await engine.run()

    assert engine.state is State.SHUTDOWN
    assert engine.orb_high == 451.0
    assert engine.orb_low == 449.0
    assert engine.signal is not None and engine.signal.signal_type.value == "BUY"
    assert engine.gex is not None
    assert engine.gex.highest_gex_strike == 455.0


@pytest.mark.asyncio
async def test_replay_mode_never_places_an_order(engine):
    await engine.run()
    assert engine.ib.placed == []


@pytest.mark.asyncio
async def test_replay_uses_delayed_market_data_type(engine):
    await engine.run()
    assert engine.ib.market_data_type == 3


@pytest.mark.asyncio
async def test_live_account_aborts_before_any_data_request():
    engine = Engine(make_config(), gate=RejectAllGate())
    engine.ib = FakeIB(opening_range_bars(), breakout_session_bars(), accounts=("U1234567",))
    engine.contract = FakeContract()

    with pytest.raises(Exception, match="Non-paper account"):
        await engine.run()

    assert engine.ib.market_data_type is None  # never got as far as requesting data


@pytest.mark.asyncio
async def test_no_opening_range_bars_shuts_down_cleanly(engine):
    engine.ib.orb_bars = []
    await engine.run()
    assert engine.state is State.SHUTDOWN
    assert engine.signal is None


@pytest.mark.asyncio
async def test_gex_below_spot_vetoes_a_bullish_breakout(engine, monkeypatch):
    """Peak gamma below spot means the break runs away from the pin -- no trade."""

    # 449 is inside the selected window and below the ~453 breakout price.
    def gex_below(contract, generic_ticks="", snapshot=False, regulatory=False):
        gamma = 0.09 if contract.strike == 449.0 else 0.01
        return FakeTicker(
            contract=contract,
            modelGreeks=FakeGreeks(gamma=gamma),
            callOpenInterest=5000 if contract.right == "C" else 0,
            putOpenInterest=1000 if contract.right == "P" else 0,
        )

    monkeypatch.setattr(engine.ib, "reqMktData", gex_below)
    await engine.run()

    assert engine.gex.highest_gex_strike == 449.0
    assert engine.signal.signal_type.value == "BUY"
    assert engine.ib.placed == []  # bullish break away from the pin: vetoed


@pytest.mark.asyncio
async def test_gex_expiration_is_taken_from_the_replay_session(engine, monkeypatch):
    """The analyzer must be asked for the session's expiry, not today's."""
    seen = {}

    from trading_engine.strategy import gex as gex_mod

    original = gex_mod.GEXAnalyzer.find_target_expiration

    def spy(self, expirations, today=None):
        seen["today"] = today
        return original(self, expirations, today=today)

    monkeypatch.setattr(gex_mod.GEXAnalyzer, "find_target_expiration", spy)
    await engine.run()

    assert seen["today"] == SESSION, f"expected the replay date {SESSION}, got {seen['today']}"


@pytest.mark.asyncio
async def test_replayed_gex_is_flagged_when_not_point_in_time(engine):
    """The fake chain offers 20260826/20260828; the session is 2026-08-26."""
    await engine.run()
    assert engine.gex is not None
    assert engine.gex.as_of == SESSION
    assert engine.gex.point_in_time is True  # fake chain still has the session's expiry


# ------------------------------------------------------ data config shape

def test_nested_data_config_is_read():
    from trading_engine.config import DataConfig

    cfg = DataConfig.model_validate({
        "mode": "delayed",
        "replay": {"date": "2026-08-26", "bar_size": "1 min"},
        "delayed": {"bar_size": "5 secs", "poll_seconds": 10},
    })
    assert cfg.mode.value == "delayed"
    assert cfg.replay.bar_size == "1 min"
    assert cfg.delayed.bar_size == "5 secs"
    assert cfg.delayed.poll_seconds == 10


def test_legacy_flat_keys_still_work():
    """An existing config must not silently lose its settings."""
    from trading_engine.config import DataConfig

    cfg = DataConfig.model_validate({
        "mode": "replay",
        "replay_date": "2026-08-26",
        "replay_bar_size": "1 min",
        "delayed_poll_seconds": 15,
    })
    assert str(cfg.replay.date) == "2026-08-26"
    assert cfg.replay.bar_size == "1 min"
    assert cfg.delayed.poll_seconds == 15


def test_nested_wins_over_legacy_when_both_present():
    from trading_engine.config import DataConfig

    cfg = DataConfig.model_validate({
        "mode": "replay",
        "replay_bar_size": "1 min",
        "replay": {"bar_size": "5 secs"},
    })
    assert cfg.replay.bar_size == "5 secs"


def test_both_sections_exist_regardless_of_mode():
    """Switching modes must not require editing the other section."""
    from trading_engine.config import DataConfig

    cfg = DataConfig.model_validate({"mode": "realtime"})
    assert cfg.replay is not None and cfg.delayed is not None
