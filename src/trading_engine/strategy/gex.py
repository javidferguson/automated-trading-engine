"""Stage 3: Gamma Exposure (GEX) analysis.

Finds the strike carrying the largest absolute dealer gamma exposure, used to
confirm or veto the breakout signal.

    GEX_strike = (gamma_call * OI_call - gamma_put * OI_put) * multiplier

The strike with the largest |GEX| is the one price is most likely to be pinned
to or repelled from, so the engine only trades a breakout heading *towards* it.

Rewritten from Bot_ORB_Gamma/strategy/gex_analyzer.py for ib_async. Three
substantive fixes over the original:

1. Subscriptions are concurrent. The original walked strikes one at a time with
   a 10-second timeout each -- 120 strikes x 2 rights is up to ~40 minutes, and
   this runs *during* a live breakout. ib_async lets every contract be in flight
   at once, so the whole scan is bounded by one timeout.
2. No shared-queue draining. The original popped ticks off shared queues with
   get_nowait() and discarded any belonging to another reqId, silently losing
   data whenever requests overlapped. ib_async's per-Ticker model removes the
   failure entirely.
3. Expiration matching is nearest-forward rather than exact. The original
   required an exact date match, so DTE=0 on any non-expiration day aborted the
   run instead of falling through to the next available expiry.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, datetime, timedelta
from typing import Optional

from ib_async import IB, Contract, Option, Ticker

from ..models import GEXResult

logger = logging.getLogger(__name__)

# IB generic tick 100 = Option Volume, 101 = Option Open Interest.
# Model greeks arrive automatically on option contracts.
OPTION_GENERIC_TICKS = "100,101"


def _is_valid(value: Optional[float]) -> bool:
    return value is not None and not math.isnan(value) and value != 0


def select_chain(chains: list, symbol: str):
    """Pick the standard option chain for an underlying.

    Select by tradingClass, NOT by exchange.

    reqSecDefOptParams returns one entry per exchange x tradingClass. For SPY
    that is ~20 entries, and all but one are the "2SPY" mini class carrying 3
    strikes. Preferring the SMART *exchange* picked 2SPY, leaving the scan with
    3 strikes centred nowhere near spot so no contract qualified. The standard
    class is the one whose tradingClass equals the underlying symbol -- for SPY
    that is the PHLX/SPY entry with 491 strikes.
    """
    standard = [c for c in chains if c.tradingClass == symbol]
    chain = max(standard or chains, key=lambda c: len(c.strikes))
    if not standard:
        logger.warning(
            "No chain with tradingClass == %s; falling back to the widest "
            "available (%s/%s, %d strikes).",
            symbol, chain.exchange, chain.tradingClass, len(chain.strikes),
        )
    return chain


class GEXAnalyzer:
    """Computes gamma exposure per strike for the nearest qualifying expiration."""

    def __init__(
        self,
        ib: IB,
        underlying: Contract,
        days_to_expiration: int = 0,
        strikes_quantity: int = 40,
        option_multiplier: int = 100,
        data_timeout_seconds: float = 30.0,
    ):
        self.ib = ib
        self.underlying = underlying
        self.days_to_expiration = days_to_expiration
        self.strikes_quantity = strikes_quantity
        self.option_multiplier = option_multiplier
        self.data_timeout_seconds = data_timeout_seconds

    # ------------------------------------------------------------------ #
    # Chain discovery
    # ------------------------------------------------------------------ #

    async def _get_chain(self) -> tuple[list[str], list[float], str, str]:
        """Return (expirations, strikes, exchange, trading_class) for the underlying."""
        chains = await self.ib.reqSecDefOptParamsAsync(
            self.underlying.symbol,
            "",
            self.underlying.secType,
            self.underlying.conId,
        )
        if not chains:
            raise LookupError(f"No option chain returned for {self.underlying.symbol}")

        # Select by tradingClass, NOT by exchange.
        #
        # reqSecDefOptParams returns one entry per exchange x tradingClass. For
        # SPY that is ~20 entries, and all but one are the "2SPY" mini class
        # with 3 strikes. Preferring the SMART *exchange* picked 2SPY and left
        # the scan with 3 strikes centred nowhere near spot, so every contract
        # failed to qualify. The standard class is the one whose tradingClass
        # equals the underlying symbol -- for SPY that is the PHLX/SPY entry
        # with 491 strikes.
        chain = select_chain(chains, self.underlying.symbol)

        logger.info(
            "Option chain: exchange=%s tradingClass=%s (%d expirations, %d strikes)",
            chain.exchange,
            chain.tradingClass,
            len(chain.expirations),
            len(chain.strikes),
        )
        # Build contracts on SMART so IB routes them, rather than pinning to
        # whichever exchange happened to supply the chain parameters.
        return sorted(chain.expirations), sorted(chain.strikes), "SMART", chain.tradingClass

    def find_target_expiration(
        self, expirations: list[str], today: Optional[date] = None
    ) -> Optional[str]:
        """Pick the nearest expiration at or after `today` + days_to_expiration.

        `today` is the session being analysed, NOT the wall clock. In replay it
        is the replay date, so DTE=0 means "expiring on the replayed session"
        rather than "expiring today" -- previously this defaulted to
        date.today() and a June replay scanned an August expiration.

        The original required an exact match, which meant DTE=0 aborted on any
        day the underlying had no expiry. Falling forward is both safer and what
        a human would do.
        """
        today = today or date.today()
        target = today + timedelta(days=self.days_to_expiration)

        candidates = []
        for text in expirations:
            try:
                parsed = datetime.strptime(text, "%Y%m%d").date()
            except ValueError:
                logger.warning("Skipping unparseable expiration %r", text)
                continue
            if parsed >= target:
                candidates.append((parsed, text))

        if not candidates:
            return None

        chosen_date, chosen = min(candidates)
        if chosen_date != target:
            logger.warning(
                "No expiration on %s; falling forward to nearest available: %s",
                target,
                chosen,
            )
        return chosen

    def select_strikes(self, strikes: list[float], spot_price: float) -> list[float]:
        """Take strikes_quantity strikes centred on the one nearest spot."""
        if not strikes:
            return []
        centre = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot_price))
        half = self.strikes_quantity // 2
        return strikes[max(0, centre - half) : min(len(strikes), centre + half + 1)]

    # ------------------------------------------------------------------ #
    # Market data
    # ------------------------------------------------------------------ #

    async def _await_option_data(self, tickers: list[Ticker]) -> None:
        """Wait until every ticker has greeks and open interest, or we time out.

        Bounded by one timeout for the whole batch rather than one per contract.
        """
        deadline = asyncio.get_running_loop().time() + self.data_timeout_seconds

        def ready(t: Ticker) -> bool:
            has_gamma = t.modelGreeks is not None and _is_valid(t.modelGreeks.gamma)
            oi = t.callOpenInterest if t.contract.right == "C" else t.putOpenInterest
            return has_gamma and _is_valid(oi)

        while asyncio.get_running_loop().time() < deadline:
            if all(ready(t) for t in tickers):
                return
            await asyncio.sleep(0.25)

        missing = sum(1 for t in tickers if not ready(t))
        logger.warning(
            "Timed out after %.0fs with %d/%d option contracts still incomplete; "
            "computing GEX from what arrived.",
            self.data_timeout_seconds,
            missing,
            len(tickers),
        )

    def _gex_from_tickers(self, tickers: list[Ticker]) -> dict[float, float]:
        """Fold per-contract tickers into per-strike gamma exposure."""
        by_strike: dict[float, float] = {}

        for ticker in tickers:
            contract = ticker.contract
            greeks = ticker.modelGreeks
            if greeks is None or not _is_valid(greeks.gamma):
                continue

            open_interest = (
                ticker.callOpenInterest if contract.right == "C" else ticker.putOpenInterest
            )
            if not _is_valid(open_interest):
                continue

            exposure = greeks.gamma * open_interest * self.option_multiplier
            # Dealers are short calls and long puts against customer flow, so put
            # gamma enters with the opposite sign.
            if contract.right == "P":
                exposure = -exposure

            by_strike[contract.strike] = by_strike.get(contract.strike, 0.0) + exposure

        return by_strike

    # ------------------------------------------------------------------ #
    # Orchestration
    # ------------------------------------------------------------------ #

    async def analyze(
        self, spot_price: float, as_of: Optional[date] = None
    ) -> Optional[GEXResult]:
        """Run the full GEX scan.

        `as_of` is the session being analysed. Returns None if GEX could not be
        computed at all.
        """
        as_of = as_of or date.today()
        expirations, strikes, exchange, trading_class = await self._get_chain()

        expiration = self.find_target_expiration(expirations, today=as_of)
        if expiration is None:
            logger.error("No expiration at or after DTE=%d", self.days_to_expiration)
            return None

        # IB drops expired contracts from the chain, so the expiration we want
        # for a past session simply is not offered. Say so loudly rather than
        # silently scanning a different expiry than the one requested.
        wanted = as_of + timedelta(days=self.days_to_expiration)
        point_in_time = datetime.strptime(expiration, "%Y%m%d").date() == wanted
        if not point_in_time:
            logger.warning(
                "GEX is NOT point-in-time: wanted the %s expiration for session %s, "
                "but IB only offers %s onward (expired contracts are removed from "
                "the chain). Scanning %s instead -- this reflects TODAY's option "
                "positioning, not %s. Treat the result as indicative only.",
                wanted, as_of, min(expirations), expiration, as_of,
            )

        selected = self.select_strikes(strikes, spot_price)
        if not selected:
            logger.error("No strikes available near spot %.2f", spot_price)
            return None

        logger.info(
            "GEX scan: %d strikes around %.2f for expiration %s",
            len(selected),
            spot_price,
            expiration,
        )

        contracts = [
            Option(
                self.underlying.symbol,
                expiration,
                strike,
                right,
                exchange,
                tradingClass=trading_class,
                currency=self.underlying.currency,
            )
            for strike in selected
            for right in ("C", "P")
        ]

        qualified = await self.ib.qualifyContractsAsync(*contracts)
        qualified = [c for c in qualified if c is not None and c.conId]
        if not qualified:
            logger.error("No option contracts qualified for expiration %s", expiration)
            return None

        logger.info("Subscribing to %d option contracts concurrently", len(qualified))
        tickers = [
            self.ib.reqMktData(c, OPTION_GENERIC_TICKS, False, False) for c in qualified
        ]

        try:
            await self._await_option_data(tickers)
            by_strike = self._gex_from_tickers(tickers)
        finally:
            for contract in qualified:
                self.ib.cancelMktData(contract)

        if not by_strike:
            logger.error(
                "No option returned both gamma and open interest. Without a market "
                "data subscription this is expected outside RTH."
            )
            return None

        highest = max(by_strike, key=lambda k: abs(by_strike[k]))
        result = GEXResult(
            as_of=as_of,
            point_in_time=point_in_time,
            expiration=expiration,
            highest_gex_strike=highest,
            highest_gex_value=by_strike[highest],
            gex_by_strike=by_strike,
            strikes_analyzed=len(selected),
            strikes_with_data=len(by_strike),
        )

        logger.info(
            "GEX complete: peak strike %.2f (GEX %.0f) from %d/%d strikes with data",
            result.highest_gex_strike,
            result.highest_gex_value,
            result.strikes_with_data,
            result.strikes_analyzed,
        )
        return result
