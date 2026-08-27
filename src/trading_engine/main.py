"""Entry point for the ORB + GEX engine.

    python -m trading_engine.main [--config PATH] [--data-mode MODE] [--replay-date YYYY-MM-DD]

DATA_MODE (env) or --data-mode selects where bars come from:
    realtime  live 5-second bars (needs a paid IB market data subscription)
    delayed   polled historical bars, ~15 min behind -- observation only
    replay    a past session re-fed; never places an order
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import nest_asyncio

from .config import load_config
from .engine import Engine, EngineStartupError
from .logging_setup import setup_logging
from .models import DataMode

nest_asyncio.apply()

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ORB + Gamma Exposure trading engine")
    parser.add_argument("--config", help="Path to the engine YAML config")
    parser.add_argument(
        "--data-mode",
        choices=[m.value for m in DataMode],
        help="Override DATA_MODE for this run",
    )
    parser.add_argument("--replay-date", help="Session to replay (YYYY-MM-DD), for --data-mode replay")
    parser.add_argument("--log-level", help="DEBUG, INFO, WARNING, ERROR")
    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> int:
    setup_logging(args.log_level)

    config = load_config(args.config)

    # CLI beats env beats YAML.
    if args.data_mode:
        config.data.mode = DataMode(args.data_mode)
    if args.replay_date:
        from datetime import date

        config.data.replay_date = date.fromisoformat(args.replay_date)

    engine = Engine(config)
    try:
        await engine.run()
    except EngineStartupError:
        return 1  # engine.run() already logged the guidance; don't repeat it
    except Exception as exc:
        logger.error("Engine stopped: %s", exc)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    # Parsed out here on purpose: argparse raises SystemExit for --help and for
    # bad arguments, and letting that escape through asyncio.run() prints a
    # traceback over the help text.
    args = parse_args(argv)
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
