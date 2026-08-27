"""The ORB + GEX engine state machine.

    CONNECTING
      -> GETTING_OPENING_RANGE      first 30 minutes: derive HIGH/LOW levels
      -> MONITORING_BREAKOUT        watch candles for a clean-body break
      -> ANALYZING_GEX              find the strike with peak gamma exposure
      -> PENDING_TRADE_EXECUTION    price it, confirm with the human, submit
      -> MONITORING_POSITION        stay attached until the bracket resolves
      -> SHUTDOWN

Ported from Bot_ORB_Gamma/core/engine.py. Two substantive changes:

* ``MONITORING_POSITION`` is new. The original shut down immediately after
  submitting, so a rejected parent order was never noticed and the bracket was
  never watched.
* The blocking ``queue.get(timeout=...)`` loops are now async, and bars arrive
  from an injected :class:`BarSource` rather than a direct reqRealTimeBars call,
  so DATA_MODE selects the source without the state machine knowing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from enum import Enum
from typing import Optional

from ib_async import IB, Contract, Index, Stock

from .bars.base import bar_from_ib, make_bar_source
from .config import EngineConfig
from .execution.confirmation import CLIConfirmationGate, ConfirmationGate
from .execution.journal import Journal
from .execution.order_manager import OrderManager, decide_trade, snap_to_strike
from .execution.safety import assert_paper_account
from .models import DataMode, GEXResult, Signal, SignalType
from .strategy.breakout import BreakoutStrategy
from .strategy.gex import GEXAnalyzer
from .strategy.opening_range import OpeningRangeStrategy

logger = logging.getLogger(__name__)


class EngineStartupError(RuntimeError):
    """The engine could not start. Carries operator guidance, not a stack trace."""


class State(str, Enum):
    INITIALIZING = "INITIALIZING"
    CONNECTING = "CONNECTING"
    GETTING_OPENING_RANGE = "GETTING_OPENING_RANGE"
    MONITORING_BREAKOUT = "MONITORING_BREAKOUT"
    ANALYZING_GEX = "ANALYZING_GEX"
    PENDING_TRADE_EXECUTION = "PENDING_TRADE_EXECUTION"
    MONITORING_POSITION = "MONITORING_POSITION"
    SHUTDOWN = "SHUTDOWN"


class Engine:
    def __init__(self, config: EngineConfig, gate: Optional[ConfirmationGate] = None):
        self.config = config
        self.state = State.INITIALIZING
        self.ib = IB()
        self.gate = gate or CLIConfirmationGate()
        self.journal = Journal()

        self.contract: Contract = self._build_contract()
        self.orb = OpeningRangeStrategy(
            market_open=config.opening_range.market_open,
            duration_minutes=config.opening_range.duration_minutes,
            exchange_tz=config.opening_range.exchange_timezone,
        )
        self.breakout: Optional[BreakoutStrategy] = None

        self.orb_high: Optional[float] = None
        self.orb_low: Optional[float] = None
        self.signal: Optional[Signal] = None
        self.spot_price: Optional[float] = None
        self.gex: Optional[GEXResult] = None
        self.accounts: list[str] = []
        self._trades: list = []

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #

    def _build_contract(self) -> Contract:
        instrument = self.config.instrument
        if instrument.sec_type.upper() == "IND":
            return Index(instrument.ticker, instrument.exchange, instrument.currency)
        return Stock(instrument.ticker, instrument.exchange, instrument.currency)

    @property
    def session_date(self) -> date:
        """The trading day being analysed -- the replay date, or today."""
        if self.config.data_mode is DataMode.REPLAY and self.config.data.replay_date:
            return self.config.data.replay_date
        return date.today()

    def _banner(self) -> None:
        """One line that pins down which combination is actually running.

        When something looks wrong three days from now, this is the line that
        says whether it was replayed data, delayed data, or the real thing --
        and which account it was pointed at.
        """
        mode = self.config.data_mode
        logger.info("=" * 68)
        logger.info("ORB + GEX ENGINE")
        logger.info(
            "  DATA_MODE   : %-9s (market data type %d, can trade: %s)",
            mode.value,
            mode.market_data_type,
            mode.can_trade,
        )
        logger.info("  Account(s)  : %s", ", ".join(self.accounts) or "unknown")
        logger.info("  Instrument  : %s %s @ %s", self.contract.symbol,
                    self.config.instrument.sec_type, self.contract.exchange)
        logger.info("  Session     : %s", self.session_date)
        logger.info("  Opening rng : %s for %d min (%s)",
                    self.config.opening_range.market_open_time,
                    self.config.opening_range.duration_minutes,
                    self.config.opening_range.exchange_timezone)
        logger.info("  Candle size : %ds", self.config.breakout.bar_size_seconds)
        if not mode.can_trade:
            logger.info("  >> Replay mode: no order will be placed.")
        logger.info("=" * 68)

    # ------------------------------------------------------------------ #
    # States
    # ------------------------------------------------------------------ #

    async def _state_connect(self) -> None:
        conn = self.config.connection
        logger.info("Connecting to IB at %s:%d (clientId=%d)", conn.host, conn.port, conn.client_id)
        try:
            await self.ib.connectAsync(conn.host, conn.port, clientId=conn.client_id)
        except (OSError, asyncio.TimeoutError) as exc:
            # A connection failure is an operational problem, not a bug -- a
            # stack trace here just buries the thing the user needs to fix.
            raise EngineStartupError(
                f"Could not reach IB Gateway at {conn.host}:{conn.port} ({exc}).\n"
                f"  - Is the Gateway up?           make gateway-start && make gateway-check\n"
                f"  - Has it finished logging in?  make gateway-vnc\n"
                f"  - Right port? {conn.port} is the socat paper port inside the gateway\n"
                f"    container. From your Mac it is 127.0.0.1:4002 instead.\n"
                f"  - Is another client already using clientId={conn.client_id}?"
            ) from exc

        # Gate immediately on connect, before anything else touches the account.
        self.accounts = assert_paper_account(self.ib, config_is_paper=self.config.account.is_paper)

        self.ib.reqMarketDataType(self.config.data_mode.market_data_type)
        qualified = await self.ib.qualifyContractsAsync(self.contract)
        if not qualified or not qualified[0].conId:
            raise LookupError(f"Could not qualify contract for {self.config.instrument.ticker}")
        self.contract = qualified[0]

        self._banner()
        self.state = State.GETTING_OPENING_RANGE

    async def _state_get_opening_range(self) -> None:
        orb_cfg = self.config.opening_range
        tz = ZoneInfo(orb_cfg.exchange_timezone)

        # endDateTime MUST be timezone-aware. IB resolves a naive datetime in a
        # zone of its own choosing: requesting a naive 10:00 for a 30-minute
        # window returned the 10:30-10:59 bars, not 09:30-09:59, so the opening
        # range was built from the wrong half hour and every bar then fell
        # outside the filter.
        open_dt = datetime.combine(self.session_date, orb_cfg.market_open, tzinfo=tz)
        range_end = open_dt + timedelta(minutes=orb_cfg.duration_minutes)

        # Live modes must wait for the window to actually close; replay must not.
        if self.config.data_mode is not DataMode.REPLAY and datetime.now(tz) < range_end:
            wait = (range_end - datetime.now(tz)).total_seconds() + 5
            logger.info("Waiting %.0fs for the opening range to complete", wait)
            await asyncio.sleep(wait)

        duration = f"{orb_cfg.duration_minutes * 60} S"
        logger.info("Requesting opening-range bars: end=%s duration=%s size=%s",
                    range_end, duration, orb_cfg.bar_size)

        bars = await self.ib.reqHistoricalDataAsync(
            self.contract,
            endDateTime=range_end,
            durationStr=duration,
            barSizeSetting=orb_cfg.bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )

        if not bars:
            logger.error("No opening-range bars returned. Is %s a trading day?", self.session_date)
            self.state = State.SHUTDOWN
            return

        kept = sum(1 for raw in bars if self.orb.add_bar(bar_from_ib(raw)))
        logger.info("Opening range: kept %d of %d returned bars", kept, len(bars))

        self.orb_high, self.orb_low = self.orb.calculate_levels()
        if self.orb_high is None or self.orb_low is None:
            logger.error("Could not derive opening range levels. Shutting down.")
            self.state = State.SHUTDOWN
            return

        self.state = State.MONITORING_BREAKOUT

    async def _state_monitor_breakout(self) -> None:
        source = make_bar_source(self.ib, self.contract, self.config)
        self.breakout = BreakoutStrategy(
            aggregation_seconds=self.config.breakout.bar_size_seconds,
            symbol=self.contract.symbol,
            source_bar_seconds=source.source_bar_seconds,
        )

        tz = ZoneInfo(self.config.opening_range.exchange_timezone)
        range_end = datetime.combine(
            self.session_date, self.config.opening_range.market_open, tzinfo=tz
        ) + timedelta(minutes=self.config.opening_range.duration_minutes)

        logger.info(
            "Monitoring for a clean-body break of %.2f / %.2f", self.orb_high, self.orb_low
        )

        try:
            async for bar in source.stream():
                # Bars from inside the opening range defined the levels; they
                # cannot also break them. Normalise first: IB returns aware
                # timestamps intraday and naive ones for daily bars.
                bar_ts = bar.timestamp
                if bar_ts.tzinfo is None:
                    bar_ts = bar_ts.replace(tzinfo=tz)
                if bar_ts < range_end:
                    continue

                signal = self.breakout.add_realtime_bar(bar, self.orb_high, self.orb_low)
                if signal.signal_type is not SignalType.HOLD:
                    logger.info("BREAKOUT: %s at %s", signal.signal_type.value, signal.timestamp)
                    self.signal = signal
                    self.spot_price = signal.price or bar.close
                    self.journal.write(
                        "breakout",
                        signal=signal,
                        orb_high=self.orb_high,
                        orb_low=self.orb_low,
                        data_mode=self.config.data_mode.value,
                    )
                    self.state = State.ANALYZING_GEX
                    return
            else:
                # Stream ended (replay exhausted / session over) with no break.
                final = self.breakout.flush_pending(self.orb_high, self.orb_low)
                if final.signal_type is not SignalType.HOLD:
                    self.signal = final
                    self.spot_price = final.price
                    self.state = State.ANALYZING_GEX
                    return
                logger.info("Bar stream ended with no breakout. Nothing to trade today.")
                self.state = State.SHUTDOWN
        finally:
            await source.close()

    async def _state_analyze_gex(self) -> None:
        analyzer = GEXAnalyzer(
            self.ib,
            self.contract,
            days_to_expiration=self.config.gex.days_to_expiration,
            strikes_quantity=self.config.gex.strikes_quantity,
            option_multiplier=self.config.gex.option_multiplier,
            data_timeout_seconds=self.config.gex.data_timeout_seconds,
        )

        self.gex = await analyzer.analyze(self.spot_price)
        if self.gex is None:
            logger.error("GEX analysis produced no result. Shutting down without trading.")
            self.state = State.SHUTDOWN
            return

        self.journal.write("gex", gex=self.gex, spot_price=self.spot_price)
        self.state = State.PENDING_TRADE_EXECUTION

    async def _state_execute_trade(self) -> None:
        right = decide_trade(self.signal, self.spot_price, self.gex.highest_gex_strike)
        if right is None:
            self.journal.write("no_trade", reason="gex_did_not_confirm", signal=self.signal)
            self.state = State.SHUTDOWN
            return

        if not self.config.data_mode.can_trade:
            logger.info(
                "Replay mode: would have bought a %s at the strike nearest %.2f, "
                "expiration %s. No order placed.",
                right.value,
                self.spot_price,
                self.gex.expiration,
            )
            self.journal.write("would_trade", right=right.value, gex=self.gex, signal=self.signal)
            self.state = State.SHUTDOWN
            return

        strike = snap_to_strike(self.spot_price, sorted(self.gex.gex_by_strike))
        if strike is None:
            logger.error("No strike available near spot %.2f", self.spot_price)
            self.state = State.SHUTDOWN
            return

        manager = OrderManager(
            self.ib,
            self.contract,
            self.config.trade_execution,
            self.config.data_mode,
            self.gate,
            self.journal,
            account_is_paper=self.config.account.is_paper,
        )

        option = manager.option_contract(
            expiration=self.gex.expiration,
            strike=strike,
            right=right,
            exchange=self.contract.exchange,
        )
        qualified = await self.ib.qualifyContractsAsync(option)
        if not qualified or not qualified[0].conId:
            logger.error("Could not qualify %s %s %s", strike, right.value, self.gex.expiration)
            self.journal.write("no_trade", reason="unqualifiable_option", strike=strike)
            self.state = State.SHUTDOWN
            return
        option = qualified[0]

        entry_price = await manager.fetch_mid_price(option)
        if entry_price is None:
            logger.error("Could not price the option. Refusing to guess an entry. Shutting down.")
            self.journal.write("no_trade", reason="unpriceable_option", strike=strike)
            self.state = State.SHUTDOWN
            return

        decision = manager.build_decision(
            self.signal, self.spot_price, self.gex, strike, entry_price, right
        )
        trades = await manager.place(option, decision)

        self.state = State.MONITORING_POSITION if trades else State.SHUTDOWN
        self._trades = trades or []

    async def _state_monitor_position(self) -> None:
        """Stay attached until the bracket resolves.

        The original engine shut down here, which meant a rejected parent order
        went unnoticed and the take-profit / stop-loss legs were never observed.
        """
        logger.info("Monitoring %d bracket legs. Ctrl-C to detach.", len(self._trades))
        terminal = {"Filled", "Cancelled", "ApiCancelled", "Inactive"}

        while True:
            statuses = {t.order.orderId: t.orderStatus.status for t in self._trades}
            parent = self._trades[0]

            if parent.orderStatus.status in {"Cancelled", "ApiCancelled", "Inactive"}:
                logger.warning("Parent order did not survive: %s", parent.orderStatus.status)
                self.state = State.SHUTDOWN
                return

            if all(s in terminal for s in statuses.values()):
                logger.info("Bracket resolved: %s", statuses)
                self.journal.write("bracket_resolved", statuses=statuses)
                self.state = State.SHUTDOWN
                return

            await asyncio.sleep(5)

    # ------------------------------------------------------------------ #
    # Loop
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        self.state = State.CONNECTING
        handlers = {
            State.CONNECTING: self._state_connect,
            State.GETTING_OPENING_RANGE: self._state_get_opening_range,
            State.MONITORING_BREAKOUT: self._state_monitor_breakout,
            State.ANALYZING_GEX: self._state_analyze_gex,
            State.PENDING_TRADE_EXECUTION: self._state_execute_trade,
            State.MONITORING_POSITION: self._state_monitor_position,
        }

        try:
            while self.state is not State.SHUTDOWN:
                handler = handlers.get(self.state)
                if handler is None:
                    logger.error("No handler for state %s", self.state)
                    break
                logger.info("--- %s ---", self.state.value)
                await handler()
        except KeyboardInterrupt:
            logger.warning("Interrupted; shutting down.")
        except EngineStartupError as exc:
            logger.error("%s", exc)
            raise
        except Exception:
            logger.exception("Unhandled error in the engine")
            raise
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IB")
        self.state = State.SHUTDOWN
