"""Logging configuration."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "orb_gamma.log"


def setup_logging(level: str | None = None) -> None:
    resolved = (level or os.getenv("LOG_LEVEL") or "INFO").upper()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(LOG_FILE))
    except OSError:
        # A read-only mount should not stop the engine from running.
        print(f"WARNING: could not open {LOG_FILE}; logging to stdout only", file=sys.stderr)

    logging.basicConfig(
        level=resolved,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )

    # ib_async is extremely chatty at DEBUG and drowns the engine's own output.
    logging.getLogger("ib_async").setLevel(logging.WARNING)
