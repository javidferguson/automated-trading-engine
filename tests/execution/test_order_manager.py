"""Trade decision rule, strike snapping, and bracket pricing.

Ported and expanded from Bot_ORB_Gamma/tests/execution/test_order_manager.py.
The original asserted only that the decision function returned the right side;
it could not catch the hardcoded $1.50 entry price, because that was applied
after the decision.
"""

from datetime import datetime

import pytest

from trading_engine.config import TradeExecutionConfig
from trading_engine.execution.order_manager import (
    OrderManager,
    decide_trade,
    snap_to_strike,
)
from trading_engine.models import (
    DataMode,
    GEXResult,
    OptionRight,
    Signal,
    SignalType,
)

SPOT = 450.0


def signal(kind: SignalType) -> Signal:
    return Signal(
        timestamp=datetime(2026, 8, 26, 10, 5),
        symbol="SPY",
        signal_type=kind,
        strategy="BreakoutStrategy",
        price=SPOT,
    )


# ------------------------------------------------------------- decision rule

def test_bullish_signal_with_gex_above_spot_buys_a_call():
    assert decide_trade(signal(SignalType.BUY), SPOT, highest_gex_strike=455.0) is OptionRight.CALL


def test_bearish_signal_with_gex_below_spot_buys_a_put():
    assert decide_trade(signal(SignalType.SELL), SPOT, highest_gex_strike=445.0) is OptionRight.PUT


def test_bullish_signal_with_gex_below_spot_is_vetoed():
    """A break away from the gamma peak is exactly the case to sit out."""
    assert decide_trade(signal(SignalType.BUY), SPOT, highest_gex_strike=445.0) is None


def test_bearish_signal_with_gex_above_spot_is_vetoed():
    assert decide_trade(signal(SignalType.SELL), SPOT, highest_gex_strike=455.0) is None


def test_hold_signal_never_trades():
    assert decide_trade(signal(SignalType.HOLD), SPOT, highest_gex_strike=455.0) is None


def test_gex_exactly_at_spot_is_vetoed():
    assert decide_trade(signal(SignalType.BUY), SPOT, highest_gex_strike=SPOT) is None


# ----------------------------------------------------------- strike snapping

def test_snap_uses_the_real_chain_not_a_five_dollar_grid():
    """SPY strikes are $1 apart; round(spot/5)*5 would have produced 450."""
    strikes = [449.0, 450.0, 451.0, 452.0, 453.0]
    assert snap_to_strike(452.4, strikes) == 452.0


def test_snap_picks_the_nearest_strike():
    assert snap_to_strike(452.6, [449.0, 450.0, 451.0, 452.0, 453.0]) == 453.0


def test_snap_handles_five_dollar_grids_too():
    assert snap_to_strike(4497.0, [4490.0, 4495.0, 4500.0]) == 4495.0


def test_snap_returns_none_for_an_empty_chain():
    assert snap_to_strike(450.0, []) is None


# ---------------------------------------------------------- bracket pricing

@pytest.fixture
def manager():
    class FakeUnderlying:
        symbol = "SPY"
        currency = "USD"

    return OrderManager(
        ib=None,
        underlying=FakeUnderlying(),
        config=TradeExecutionConfig(quantity=2, take_profit_percentage=0.20, stop_loss_percentage=0.30),
        data_mode=DataMode.REPLAY,
        gate=None,
        journal=None,
    )


@pytest.fixture
def gex():
    return GEXResult(expiration="20260826", highest_gex_strike=455.0, highest_gex_value=1e6)


def test_bracket_levels_derive_from_the_real_entry_price(manager, gex):
    """The regression test for `entry_price = 1.50  # Placeholder`."""
    decision = manager.build_decision(
        signal(SignalType.BUY), SPOT, gex, strike=450.0, entry_price=3.40, right=OptionRight.CALL
    )

    assert decision.entry_price == 3.40
    assert decision.take_profit_price == pytest.approx(4.08)  # +20%
    assert decision.stop_loss_price == pytest.approx(2.38)    # -30%


def test_bracket_levels_track_a_different_entry_price(manager, gex):
    decision = manager.build_decision(
        signal(SignalType.BUY), SPOT, gex, strike=450.0, entry_price=1.50, right=OptionRight.CALL
    )
    assert decision.take_profit_price == pytest.approx(1.80)
    assert decision.stop_loss_price == pytest.approx(1.05)


def test_quantity_comes_from_config(manager, gex):
    decision = manager.build_decision(
        signal(SignalType.BUY), SPOT, gex, strike=450.0, entry_price=3.40, right=OptionRight.CALL
    )
    assert decision.quantity == 2
    assert decision.total_debit == pytest.approx(680.0)  # 3.40 * 2 * 100


def test_quantity_above_the_cap_is_refused_at_construction():
    class FakeUnderlying:
        symbol = "SPY"
        currency = "USD"

    with pytest.raises(ValueError, match="max_quantity"):
        OrderManager(
            ib=None,
            underlying=FakeUnderlying(),
            config=TradeExecutionConfig(quantity=10, max_quantity=5),
            data_mode=DataMode.REPLAY,
            gate=None,
            journal=None,
        )


def test_require_confirmation_cannot_be_disabled():
    """There is deliberately no config path to an unattended live order."""
    with pytest.raises(ValueError, match="require_confirmation cannot be false"):
        TradeExecutionConfig(require_confirmation=False)
