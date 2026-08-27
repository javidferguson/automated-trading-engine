#!/usr/bin/env python3
"""Barebones IB connection check. No Docker, no config files, no strategy.

Answers exactly one question: can we talk to IB, and is it a paper account?

Run it against whatever is listening -- native TWS, native IB Gateway, or the
Docker container. Defaults to native TWS paper on 127.0.0.1:7497.

    python scripts/check_ib_connection.py                 # TWS paper   (7497)
    python scripts/check_ib_connection.py --port 4002     # Gateway paper
    python scripts/check_ib_connection.py --port 4004 --host ajj-ib-gateway

Common ports:
    7497  native TWS         paper
    7496  native TWS         live
    4002  native IB Gateway  paper
    4001  native IB Gateway  live
    4004  Docker gateway container, socat paper relay
"""

from __future__ import annotations

import argparse
import socket
import sys

PAPER_PREFIXES = ("DU", "DF")


def check_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Is anything listening? Separates 'nothing there' from 'API said no'."""
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Check the IB API connection.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--client-id", type=int, default=99,
                    help="Use something unused; a clash silently fails to connect.")
    ap.add_argument("--symbol", default="SPY", help="Symbol for the optional data check")
    ap.add_argument("--allow-live", action="store_true",
                    help="Permit a non-paper account (prints a warning; still places no orders)")
    args = ap.parse_args()

    print(f"\n1. Is anything listening on {args.host}:{args.port}?")
    if not check_port(args.host, args.port):
        print(f"   NO -- nothing is accepting connections there.\n")
        print("   Start TWS or IB Gateway, log in, and enable the API:")
        print("     TWS:     File > Global Configuration > API > Settings")
        print("     Gateway: Configure > Settings > API > Settings")
        print("   Tick 'Enable ActiveX and Socket Clients', untick 'Read-Only API',")
        print("   add 127.0.0.1 to Trusted IPs, and confirm the socket port matches.")
        return 1
    print("   YES")

    try:
        from ib_async import IB, Stock, util
    except ImportError:
        print("\n   ib_async is not installed:  pip install ib_async")
        return 1

    util.logToConsole("ERROR")  # keep ib_async quiet; we do our own reporting
    ib = IB()

    print(f"\n2. Connecting (clientId={args.client_id})...")
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=15)
    except Exception as exc:
        print(f"   FAILED: {exc}\n")
        print("   The port is open but the API handshake did not complete. Usually:")
        print("     - the API is not enabled in TWS/Gateway settings")
        print("     - 127.0.0.1 is not in Trusted IPs")
        print(f"     - clientId {args.client_id} is already in use by another client")
        print("     - TWS/Gateway is still logging in (or waiting on 2FA)")
        return 1
    print("   CONNECTED")

    try:
        accounts = ib.managedAccounts()
        print(f"\n3. Accounts: {', '.join(accounts) if accounts else '(none reported)'}")
        if not accounts:
            print("   No accounts reported -- refusing to call this a working setup.")
            return 1

        live = [a for a in accounts if not a.startswith(PAPER_PREFIXES)]
        if live:
            print(f"   WARNING: non-paper account(s) present: {live}")
            print(f"   Paper accounts start with {' or '.join(PAPER_PREFIXES)}.")
            if not args.allow_live:
                print("   Refusing to continue. Re-run with --allow-live if this is intended.")
                return 1
        else:
            print("   All accounts are paper. Good.")

        print(f"\n4. Server time: {ib.reqCurrentTime()}")

        print(f"\n5. Requesting delayed daily bars for {args.symbol}...")
        ib.reqMarketDataType(3)  # delayed; needs no market data subscription
        contract = Stock(args.symbol, "SMART", "USD")
        qualified = ib.qualifyContracts(contract)
        if not qualified or not qualified[0].conId:
            print(f"   Could not qualify {args.symbol}. Connection is fine; the symbol is not.")
            return 0

        bars = ib.reqHistoricalData(
            qualified[0], endDateTime="", durationStr="5 D",
            barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
        )
        if not bars:
            print("   No bars returned. The connection works, but market data did not arrive.")
            print("   Outside market hours this can be normal.")
        else:
            print(f"   Got {len(bars)} bars. Most recent:")
            b = bars[-1]
            print(f"     {b.date}  O={b.open} H={b.high} L={b.low} C={b.close}")
            print(f"\n   Bar timestamp type: {'timezone-aware' if getattr(b.date, 'tzinfo', None) else 'naive'}")
            print("   (naive means the timestamps are in the Gateway/TWS timezone --")
            print("    it must match the exchange or the opening-range filter drops everything)")

        print("\nAll checks passed. The API connection works.\n")
        return 0
    finally:
        ib.disconnect()


if __name__ == "__main__":
    sys.exit(main())
