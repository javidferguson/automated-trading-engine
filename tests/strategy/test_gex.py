"""GEX analyzer: expiration selection, strike windowing, and the GEX fold.

These cover the pure logic. The IB round-trip in ``analyze()`` is exercised by
the replay run rather than mocked here.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pytest

from trading_engine.strategy.gex import GEXAnalyzer


@dataclass
class FakeContract:
    strike: float
    right: str
    symbol: str = "SPY"


@dataclass
class FakeGreeks:
    gamma: Optional[float]


@dataclass
class FakeTicker:
    contract: FakeContract
    modelGreeks: Optional[FakeGreeks]
    callOpenInterest: float = 0.0
    putOpenInterest: float = 0.0


class FakeUnderlying:
    symbol = "SPY"
    secType = "STK"
    exchange = "SMART"
    currency = "USD"
    conId = 756733


@pytest.fixture
def analyzer():
    return GEXAnalyzer(ib=None, underlying=FakeUnderlying(), strikes_quantity=4)


# ---------------------------------------------------------------- expirations

def test_exact_dte_match_is_preferred(analyzer):
    expirations = ["20260826", "20260827", "20260828"]
    assert analyzer.find_target_expiration(expirations, today=date(2026, 8, 26)) == "20260826"


def test_falls_forward_when_no_expiration_on_target_date(analyzer):
    """The original aborted here; DTE=0 on a non-expiry day must not kill the run."""
    expirations = ["20260828", "20260904"]
    assert analyzer.find_target_expiration(expirations, today=date(2026, 8, 26)) == "20260828"


def test_past_expirations_are_never_selected(analyzer):
    expirations = ["20260820", "20260825", "20260828"]
    assert analyzer.find_target_expiration(expirations, today=date(2026, 8, 26)) == "20260828"


def test_returns_none_when_all_expirations_are_in_the_past(analyzer):
    assert analyzer.find_target_expiration(["20260820"], today=date(2026, 8, 26)) is None


def test_unparseable_expirations_are_skipped(analyzer):
    expirations = ["not-a-date", "20260828"]
    assert analyzer.find_target_expiration(expirations, today=date(2026, 8, 26)) == "20260828"


def test_nonzero_dte_targets_a_later_date(analyzer):
    analyzer.days_to_expiration = 2
    expirations = ["20260826", "20260828", "20260830"]
    assert analyzer.find_target_expiration(expirations, today=date(2026, 8, 26)) == "20260828"


# ------------------------------------------------------------------- strikes

def test_select_strikes_centres_on_spot(analyzer):
    strikes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
    assert analyzer.select_strikes(strikes, spot_price=103.4) == [101.0, 102.0, 103.0, 104.0, 105.0]


def test_select_strikes_clamps_at_the_low_edge(analyzer):
    strikes = [100.0, 101.0, 102.0, 103.0]
    assert analyzer.select_strikes(strikes, spot_price=100.0) == [100.0, 101.0, 102.0]


def test_select_strikes_handles_empty_chain(analyzer):
    assert analyzer.select_strikes([], spot_price=100.0) == []


# ----------------------------------------------------------------- GEX maths

def test_call_gamma_is_positive_and_put_gamma_negative(analyzer):
    tickers = [
        FakeTicker(FakeContract(100.0, "C"), FakeGreeks(0.05), callOpenInterest=1000),
        FakeTicker(FakeContract(100.0, "P"), FakeGreeks(0.03), putOpenInterest=2000),
    ]
    # call: 0.05 * 1000 * 100 = 5000 ; put: -(0.03 * 2000 * 100) = -6000
    assert analyzer._gex_from_tickers(tickers) == {100.0: pytest.approx(-1000.0)}


def test_calls_and_puts_aggregate_per_strike(analyzer):
    tickers = [
        FakeTicker(FakeContract(100.0, "C"), FakeGreeks(0.05), callOpenInterest=1000),
        FakeTicker(FakeContract(101.0, "C"), FakeGreeks(0.04), callOpenInterest=500),
    ]
    result = analyzer._gex_from_tickers(tickers)
    assert result == {100.0: pytest.approx(5000.0), 101.0: pytest.approx(2000.0)}


def test_contracts_without_greeks_are_skipped(analyzer):
    """No subscription means no greeks -- drop the contract, don't crash."""
    tickers = [
        FakeTicker(FakeContract(100.0, "C"), None, callOpenInterest=1000),
        FakeTicker(FakeContract(101.0, "C"), FakeGreeks(0.04), callOpenInterest=500),
    ]
    assert list(analyzer._gex_from_tickers(tickers)) == [101.0]


def test_contracts_without_open_interest_are_skipped(analyzer):
    tickers = [FakeTicker(FakeContract(100.0, "C"), FakeGreeks(0.05), callOpenInterest=0)]
    assert analyzer._gex_from_tickers(tickers) == {}


def test_nan_gamma_is_skipped(analyzer):
    tickers = [FakeTicker(FakeContract(100.0, "C"), FakeGreeks(float("nan")), callOpenInterest=1000)]
    assert analyzer._gex_from_tickers(tickers) == {}


def test_put_open_interest_is_read_from_the_put_field(analyzer):
    """A put carrying only callOpenInterest must not be counted."""
    tickers = [FakeTicker(FakeContract(100.0, "P"), FakeGreeks(0.03), callOpenInterest=9999)]
    assert analyzer._gex_from_tickers(tickers) == {}


# --------------------------------------------------------- chain selection
#
# reqSecDefOptParams returns one entry per exchange x tradingClass. Selecting by
# exchange picked SPY's "2SPY" mini class -- 3 strikes, none near spot -- so no
# contract qualified and the GEX stage produced nothing.

from dataclasses import dataclass as _dc, field as _field

from trading_engine.strategy.gex import select_chain


@_dc
class FakeChain:
    exchange: str
    tradingClass: str
    strikes: list = _field(default_factory=list)
    expirations: list = _field(default_factory=list)


def spy_chains():
    """Shaped like the real reqSecDefOptParams response for SPY."""
    real = FakeChain("PHLX", "SPY", strikes=list(range(491)), expirations=list(range(33)))
    minis = [
        FakeChain(ex, "2SPY", strikes=[668.0, 672.0, 682.0], expirations=["20260904"])
        for ex in ("SMART", "CBOE", "BATS", "ISE", "MIAX", "NASDAQOM")
    ]
    return minis[:3] + [real] + minis[3:]


def test_selects_the_chain_whose_trading_class_matches_the_symbol():
    chain = select_chain(spy_chains(), "SPY")
    assert chain.tradingClass == "SPY"
    assert len(chain.strikes) == 491


def test_does_not_select_by_exchange():
    """SMART is present but carries the 3-strike mini class."""
    chain = select_chain(spy_chains(), "SPY")
    assert chain.exchange != "SMART"


def test_picks_the_widest_when_several_share_the_trading_class():
    chains = [
        FakeChain("CBOE", "SPY", strikes=[1.0, 2.0]),
        FakeChain("PHLX", "SPY", strikes=[1.0, 2.0, 3.0, 4.0]),
    ]
    assert len(select_chain(chains, "SPY").strikes) == 4


def test_falls_back_to_the_widest_when_no_trading_class_matches():
    chains = [
        FakeChain("SMART", "2SPY", strikes=[1.0, 2.0, 3.0]),
        FakeChain("CBOE", "SPYW", strikes=list(range(50))),
    ]
    chain = select_chain(chains, "SPY")
    assert chain.tradingClass == "SPYW"
    assert len(chain.strikes) == 50


# ------------------------------------------------- session-relative expiry
#
# find_target_expiration defaulted to date.today(), so replaying a June session
# scanned an August expiration -- "0DTE" relative to the wall clock rather than
# to the session being analysed.

def test_dte_zero_is_relative_to_the_session_not_today(analyzer):
    """Replaying 2026-06-12 must target the 2026-06-12 expiry."""
    expirations = ["20260612", "20260619", "20260827"]
    chosen = analyzer.find_target_expiration(expirations, today=date(2026, 6, 12))
    assert chosen == "20260612"


def test_session_date_is_honoured_even_when_later_expiries_exist(analyzer):
    expirations = ["20260612", "20260827", "20261218"]
    assert analyzer.find_target_expiration(expirations, today=date(2026, 6, 15)) == "20260827"


def test_replaying_a_past_session_falls_forward_when_the_expiry_is_gone(analyzer):
    """IB removes expired contracts, so a past session's expiry is unavailable.

    Falling forward is the only option; the caller marks the result
    point_in_time=False so it is not mistaken for a backtest input.
    """
    live_only = ["20260827", "20260904", "20261218"]
    chosen = analyzer.find_target_expiration(live_only, today=date(2026, 6, 12))
    assert chosen == "20260827"
