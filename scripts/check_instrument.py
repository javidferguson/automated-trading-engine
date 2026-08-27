#!/usr/bin/env python3
"""Check whether an instrument is suitable for the 0DTE ORB+GEX strategy.

The code will happily trade any optionable US stock or ETF. What actually
decides suitability is **how often the underlying has an expiration**, because
`gex.days_to_expiration: 0` means "expiring on the session being traded". On a
day with no expiry the engine falls forward to the next one — which is no longer
0DTE, and the gamma-pinning premise the strategy rests on no longer holds.

    python scripts/check_instrument.py SPY QQQ NVDA VOO
    python scripts/check_instrument.py --port 4002 AAPL

Reports, per symbol: expiration cadence, whether today has one, strike spacing,
and a verdict.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
from datetime import date, datetime, timedelta

DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "VOO", "IVV", "NVDA", "AAPL", "TSLA"]


def business_days_between(start: date, end: date) -> int:
    """Trading-day gap, ignoring holidays (close enough to classify cadence)."""
    days, cursor = 0, start
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def classify(gaps: list[int]) -> tuple[str, str, bool]:
    """(cadence, verdict, is_suitable) from consecutive business-day gaps.

    Uses the median rather than the minimum: single stocks run roughly
    Mon/Wed/Fri, which produces gaps like [1, 2, 2, 3, 2]. A minimum of 1 there
    would wrongly read as daily.
    """
    if not gaps:
        return "unknown", "no expirations found", False

    median = statistics.median(gaps)
    if median <= 1:
        return "every trading day", "IDEAL -- true 0DTE every session", True
    if median <= 2.5:
        return "~Mon/Wed/Fri", "USABLE -- 0DTE on ~3 sessions a week", True
    if median <= 5.5:
        return "weekly (Fridays)", "POOR -- 0DTE only on Fridays", False
    return "monthly or sparser", "UNSUITABLE for a 0DTE strategy", False


def main() -> int:
    ap = argparse.ArgumentParser(description="Check instruments for 0DTE ORB+GEX suitability.")
    ap.add_argument("symbols", nargs="*", default=DEFAULT_SYMBOLS)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=98)
    args = ap.parse_args()

    try:
        from ib_async import IB, Stock, util
    except ImportError:
        print("ib_async is not installed:  pip install ib_async")
        return 1

    sys.path.insert(0, "src")
    from trading_engine.strategy.gex import select_chain

    util.logToConsole(logging.CRITICAL)
    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=15)
    except Exception as exc:
        print(f"Could not connect to IB at {args.host}:{args.port}: {exc}")
        print("Start the Gateway and enable the API, then retry.")
        return 1

    today = date.today()
    print(f"\n0DTE suitability  (today = {today})")
    print(f"{'symbol':<8} {'expirations':<20} {'0DTE today':<12} {'strike gap':<12} verdict")
    print("-" * 88)

    try:
        for symbol in args.symbols:
            symbol = symbol.upper()
            try:
                qualified = ib.qualifyContracts(Stock(symbol, "SMART", "USD"))
                if not qualified or not qualified[0].conId:
                    print(f"{symbol:<8} could not qualify -- check the ticker")
                    continue
                contract = qualified[0]

                chains = ib.reqSecDefOptParams(
                    contract.symbol, "", contract.secType, contract.conId
                )
                if not chains:
                    print(f"{symbol:<8} no option chain -- not optionable")
                    continue

                chain = select_chain(chains, symbol)
                expirations = sorted(
                    d
                    for d in (
                        datetime.strptime(e, "%Y%m%d").date() for e in chain.expirations
                    )
                    if d >= today
                )
                gaps = [
                    business_days_between(expirations[i], expirations[i + 1])
                    for i in range(min(5, len(expirations) - 1))
                ]
                cadence, verdict, _ = classify(gaps)

                strikes = sorted(chain.strikes)
                spacing = (
                    f"${min(round(b - a, 2) for a, b in zip(strikes, strikes[1:])):g}"
                    if len(strikes) > 1
                    else "n/a"
                )
                has_today = "yes" if today in expirations else "no"

                print(f"{symbol:<8} {cadence:<20} {has_today:<12} {spacing:<12} {verdict}")
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the sweep
                print(f"{symbol:<8} error: {str(exc)[:50]}")
    finally:
        ib.disconnect()

    print(
        "\n'0DTE today = no' after the close is normal -- that expiration has already "
        "rolled off.\nCadence is what matters, not today's answer.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
