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
