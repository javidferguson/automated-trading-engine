"""Stage 4: trade decision, pricing, and bracket order placement.

Rewritten from Bot_ORB_Gamma/execution/order_manager.py for ib_async. Four
substantive fixes over the original:

1. ``entry_price = 1.50  # Placeholder`` is gone. The original derived the entry
   limit *and* the take-profit *and* the stop-loss from a hardcoded $1.50, so
   every bracket it submitted was priced off a number nobody chose. The entry
   now comes from the option's actual mid price.
2. ``totalQuantity = 1`` is configurable, with a hard cap.
3. ``round(spot / 5) * 5`` is gone. That assumed $5 strike spacing -- right for
   SPX, wrong for SPY's $1 grid. Strikes are snapped to the real chain.
4. Order IDs are no longer ``parent + 1`` / ``parent + 2``, which collided with
   the connector's own counter. ``ib.bracketOrder()`` allocates them and sets
   the transmit flags so the group goes as one unit.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ib_async import IB, Contract, Option, Trade

from ..config import TradeExecutionConfig
from ..models import (
    DataMode,
    GEXResult,
    OptionRight,
    Signal,
    SignalType,
    TradeDecision,
)
from .confirmation import ConfirmationGate
from .journal import Journal
from .safety import assert_can_trade, assert_paper_account

logger = logging.getLogger(__name__)


@dataclass
class Preflight:
    """Broker's answer to 'what would happen if I sent this?' -- nothing is sent."""

    init_margin_change: Optional[str] = None
    maint_margin_change: Optional[str] = None
    commission: Optional[float] = None
    warning: Optional[str] = None


def snap_to_strike(spot_price: float, strikes: list[float]) -> Optional[float]:
    """Nearest available strike to spot, taken from the real chain.

    The original assumed a $5 grid via ``round(spot / 5) * 5``, which silently
    produces non-existent strikes on any underlying with different spacing.
    """
    if not strikes:
        return None
    return min(strikes, key=lambda s: abs(s - spot_price))


def decide_trade(
    signal: Signal, spot_price: float, highest_gex_strike: float
) -> Optional[OptionRight]:
    """Apply the GEX confirmation rule to a breakout signal.

    Only trade a breakout heading towards the gamma peak: a bullish break with
    the peak above spot, or a bearish break with it below. A break away from the
    peak is the case where dealer hedging is most likely to fade the move.
    """
    if signal.signal_type is SignalType.BUY and highest_gex_strike > spot_price:
        logger.info("Bullish breakout confirmed by GEX above spot: long call")
        return OptionRight.CALL

    if signal.signal_type is SignalType.SELL and highest_gex_strike < spot_price:
        logger.info("Bearish breakout confirmed by GEX below spot: long put")
        return OptionRight.PUT

    logger.info(
        "GEX does not confirm the %s signal (peak %.2f vs spot %.2f); no trade.",
        signal.signal_type.value,
        highest_gex_strike,
        spot_price,
    )
    return None


class OrderManager:
    """Builds, prices, confirms, and submits the 0DTE option bracket."""

    def __init__(
        self,
        ib: IB,
        underlying: Contract,
        config: TradeExecutionConfig,
        data_mode: DataMode,
        gate: ConfirmationGate,
        journal: Journal,
        account_is_paper: bool = True,
    ):
        self.ib = ib
        self.underlying = underlying
        self.config = config
        self.data_mode = data_mode
        self.gate = gate
        self.journal = journal
        self.account_is_paper = account_is_paper

        if config.quantity > config.max_quantity:
            raise ValueError(
                f"quantity ({config.quantity}) exceeds max_quantity ({config.max_quantity})"
            )

    # ------------------------------------------------------------------ #
    # Pricing
    # ------------------------------------------------------------------ #

    async def fetch_mid_price(self, contract: Contract, timeout: float = 10.0) -> Optional[float]:
        """The option's current mid price, or None if the market isn't quoting it."""
        [ticker] = await self.ib.reqTickersAsync(contract)

        bid, ask, last = ticker.bid, ticker.ask, ticker.last

        def valid(x) -> bool:
            return x is not None and not math.isnan(x) and x > 0

        if valid(bid) and valid(ask):
            return round((bid + ask) / 2, 2)
        if valid(last):
            logger.warning("No two-sided quote for %s; falling back to last (%.2f)", contract.localSymbol, last)
            return round(last, 2)
        if ticker.modelGreeks and valid(ticker.modelGreeks.optPrice):
            logger.warning("No quote or last for %s; falling back to model price", contract.localSymbol)
            return round(ticker.modelGreeks.optPrice, 2)

        logger.error("Could not price %s: no bid/ask, last, or model price", contract.localSymbol)
        return None

    def build_decision(
        self,
        signal: Signal,
        spot_price: float,
        gex: GEXResult,
        strike: float,
        entry_price: float,
        right: OptionRight,
    ) -> TradeDecision:
        """Assemble the bracket levels around a real entry price."""
        take_profit = round(entry_price * (1 + self.config.take_profit_percentage), 2)
        stop_loss = round(entry_price * (1 - self.config.stop_loss_percentage), 2)

        return TradeDecision(
            symbol=self.underlying.symbol,
            right=right,
            strike=strike,
            expiration=gex.expiration,
            quantity=self.config.quantity,
            entry_price=entry_price,
            take_profit_price=take_profit,
            stop_loss_price=stop_loss,
            signal=signal,
            spot_price=spot_price,
            highest_gex_strike=gex.highest_gex_strike,
        )

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #

    def option_contract(
        self,
        expiration: str,
        strike: float,
        right: OptionRight,
        exchange: str,
        trading_class: str = "",
    ) -> Option:
        """Build the option contract. Called before pricing, so it cannot take a
        TradeDecision -- the decision needs the entry price this contract supplies."""
        return Option(
            self.underlying.symbol,
            expiration,
            strike,
            right.value,
            exchange,
            tradingClass=trading_class,
            currency=self.underlying.currency,
        )

    async def preflight(self, contract: Contract, decision: TradeDecision) -> Preflight:
        """Ask IB what the order would do, without sending it."""
        probe = self.ib.bracketOrder(
            "BUY",
            decision.quantity,
            decision.entry_price,
            decision.take_profit_price,
            decision.stop_loss_price,
        ).parent

        try:
            state = await self.ib.whatIfOrderAsync(contract, probe)
        except Exception:
            logger.exception("whatIfOrder failed; continuing without a preflight estimate")
            return Preflight(warning="whatIfOrder failed -- no margin/commission estimate")

        commission = None
        if state.commission is not None and not math.isnan(state.commission):
            commission = state.commission

        return Preflight(
            init_margin_change=state.initMarginChange or None,
            maint_margin_change=state.maintMarginChange or None,
            commission=commission,
            warning=state.warningText or None,
        )

    async def place(self, contract: Contract, decision: TradeDecision) -> Optional[list[Trade]]:
        """Confirm with the human, then submit the bracket. Returns None if declined."""
        # Both gates again, immediately before submission. The one after connect
        # is not enough: a reconnect can land somewhere else in between.
        assert_can_trade(self.data_mode)
        assert_paper_account(self.ib, config_is_paper=self.account_is_paper)

        if decision.quantity > self.config.max_quantity:
            raise ValueError(
                f"Refusing {decision.quantity} contracts: max_quantity is {self.config.max_quantity}"
            )

        preflight = await self.preflight(contract, decision)

        self.journal.write(
            "proposed",
            decision=decision,
            preflight=preflight.__dict__,
            data_mode=self.data_mode.value,
        )

        if not self.gate.confirm(decision, preflight):
            self.journal.write("declined", decision=decision)
            logger.info("Order declined at the confirmation gate; nothing submitted.")
            return None

        bracket = self.ib.bracketOrder(
            "BUY",
            decision.quantity,
            decision.entry_price,
            decision.take_profit_price,
            decision.stop_loss_price,
        )
        for order in bracket:
            order.tif = "DAY"
            order.outsideRth = False

        trades = [self.ib.placeOrder(contract, order) for order in bracket]

        self.journal.write(
            "submitted",
            decision=decision,
            order_ids=[t.order.orderId for t in trades],
            parent_id=bracket.parent.orderId,
        )
        logger.info(
            "Bracket submitted: parent=%s tp=%s sl=%s",
            bracket.parent.orderId,
            bracket.takeProfit.orderId,
            bracket.stopLoss.orderId,
        )

        for trade in trades:
            trade.statusEvent += self._on_status
        return trades

    def _on_status(self, trade: Trade) -> None:
        self.journal.write(
            "status",
            order_id=trade.order.orderId,
            status=trade.orderStatus.status,
            filled=trade.orderStatus.filled,
            remaining=trade.orderStatus.remaining,
            avg_fill_price=trade.orderStatus.avgFillPrice,
            updated=datetime.now(),
        )
