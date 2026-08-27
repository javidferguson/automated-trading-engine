"""Configuration loading for the ORB + GEX engine.

YAML supplies the defaults; a small set of environment variables override them.
The one that matters most is ``DATA_MODE`` -- see :class:`~trading_engine.models.DataMode`.
"""

from __future__ import annotations

import logging
import os
from datetime import date, time
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from .models import DataMode

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config/orb-gamma-config.yaml"


class ConnectionConfig(BaseModel):
    host: str = "ajj-ib-gateway"
    port: int = 4004
    client_id: int = 2


class AccountConfig(BaseModel):
    type: str = "paper"

    @property
    def is_paper(self) -> bool:
        return self.type.lower() == "paper"


class InstrumentConfig(BaseModel):
    ticker: str = "SPY"
    sec_type: str = "STK"
    exchange: str = "SMART"
    currency: str = "USD"


class OpeningRangeConfig(BaseModel):
    market_open_time: str = "09:30:00"
    duration_minutes: int = 30
    bar_size: str = "1 min"

    @property
    def market_open(self) -> time:
        return time.fromisoformat(self.market_open_time)


class BreakoutConfig(BaseModel):
    bar_size_seconds: int = 300


class DataConfig(BaseModel):
    mode: DataMode = DataMode.REPLAY
    replay_date: Optional[date] = None
    replay_bar_size: str = "30 secs"
    replay_speed: float = 0.0

    @field_validator("mode", mode="before")
    @classmethod
    def _normalise_mode(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class GEXConfig(BaseModel):
    days_to_expiration: int = 0
    strikes_quantity: int = 40
    option_multiplier: int = 100
    data_timeout_seconds: float = 30.0


class TradeExecutionConfig(BaseModel):
    quantity: int = 1
    max_quantity: int = 5
    take_profit_percentage: float = 0.20
    stop_loss_percentage: float = 0.30
    require_confirmation: bool = True

    @field_validator("require_confirmation")
    @classmethod
    def _confirmation_is_mandatory(cls, v: bool) -> bool:
        # There is deliberately no way to turn the human gate off on this path.
        # If you want unattended runs, use DATA_MODE=replay, which cannot trade.
        if not v:
            raise ValueError(
                "require_confirmation cannot be false: every order on the ORB/GEX "
                "path requires explicit human confirmation."
            )
        return True


class EngineConfig(BaseModel):
    connection: ConnectionConfig = Field(default_factory=ConnectionConfig)
    account: AccountConfig = Field(default_factory=AccountConfig)
    instrument: InstrumentConfig = Field(default_factory=InstrumentConfig)
    opening_range: OpeningRangeConfig = Field(default_factory=OpeningRangeConfig)
    breakout: BreakoutConfig = Field(default_factory=BreakoutConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    gex: GEXConfig = Field(default_factory=GEXConfig)
    trade_execution: TradeExecutionConfig = Field(default_factory=TradeExecutionConfig)

    @property
    def data_mode(self) -> DataMode:
        return self.data.mode


def _apply_env_overrides(raw: dict) -> dict:
    """Layer environment variables over the YAML values.

    Only connection details and DATA_MODE are overridable. Strategy parameters
    stay in YAML so a run is reproducible from a file you can diff.
    """
    connection = raw.setdefault("connection", {})
    if host := os.getenv("IB_HOST"):
        connection["host"] = host
    if port := os.getenv("IB_PORT"):
        connection["port"] = int(port)
    if client_id := os.getenv("IB_CLIENT_ID"):
        connection["client_id"] = int(client_id)

    data = raw.setdefault("data", {})
    if mode := os.getenv("DATA_MODE"):
        data["mode"] = mode.strip().lower()
    if replay_date := os.getenv("REPLAY_DATE"):
        data["replay_date"] = replay_date

    # PAPER_TRADING is about the ACCOUNT, never about the data source.
    if paper := os.getenv("PAPER_TRADING"):
        raw.setdefault("account", {})["type"] = (
            "paper" if paper.strip().lower() in ("1", "true", "yes") else "live"
        )

    return raw


def load_config(config_path: str | Path | None = None) -> EngineConfig:
    """Load the engine config from YAML, then apply environment overrides."""
    path = Path(config_path or os.getenv("ORB_CONFIG_FILE") or DEFAULT_CONFIG_PATH)
    if not path.is_file():
        raise FileNotFoundError(
            f"Config file not found: {path}. Run from the repo root, or set ORB_CONFIG_FILE."
        )

    raw = yaml.safe_load(path.read_text()) or {}
    raw = _apply_env_overrides(raw)
    config = EngineConfig.model_validate(raw)

    logger.debug("Loaded config from %s", path)
    return config
