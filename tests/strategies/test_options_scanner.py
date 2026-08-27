"""Regression tests for the 0DTE options scanner's scoring and IV gate.

These lock in the three contradictions the scanner shipped with: an inverted
theta filter, a score dominated by volume, and an IV lookup whose failure mode
was indistinguishable from a pass.
"""

from dataclasses import dataclass

import pandas as pd
import pytest

from trading_engine.strategies.options_0dte.scanner import BreakoutAnalyzer


@dataclass
class Cfg:
    min_gamma: float = 0.01
    min_delta: float = 0.10
    max_delta: float = 0.90
    min_vega: float = 0.01
    min_theta: float = -0.50
    min_iv_percentile: float = 30
    max_iv_percentile: float = 70


@pytest.fixture
def analyzer(tmp_path, monkeypatch):
    # analyze_options writes a signals CSV relative to the CWD as a side effect;
    # keep that out of the repo's data/ directory during tests.
    monkeypatch.chdir(tmp_path)
    return BreakoutAnalyzer(Cfg())


def frame(rows):
    return pd.DataFrame(rows)


def option(gamma=0.05, delta=0.4, vega=0.2, theta=-0.2, volume=100, bid=1.0, ask=1.2):
    return dict(gamma=gamma, delta=delta, vega=vega, theta=theta, volume=volume, bid=bid, ask=ask)


PASSING_IV = {"iv_percentile": 50}


def test_slow_decay_options_are_kept(analyzer):
    """theta = -0.2 is slower decay than the -0.50 floor, so it must survive."""
    result = analyzer.analyze_options(frame([option(theta=-0.2)]), PASSING_IV)
    assert len(result) == 1


def test_fast_decay_options_are_filtered_out(analyzer):
    """theta = -0.9 decays faster than the floor. The original kept exactly these."""
    result = analyzer.analyze_options(frame([option(theta=-0.9)]), PASSING_IV)
    assert result.empty


def test_score_is_not_dominated_by_volume(analyzer):
    """A high-gamma option must outrank a low-gamma one with more volume.

    Under the original unnormalised score, gamma contributed ~2 points while
    volume contributed 10, so volume decided the ranking outright.
    """
    df = frame([
        option(gamma=0.01, vega=0.05, volume=1_000_000),  # huge volume, poor greeks
        option(gamma=0.20, vega=0.50, volume=10),         # great greeks, thin
    ])
    result = analyzer.analyze_options(df, PASSING_IV)
    assert result.iloc[0]["gamma"] == 0.20


def test_less_decay_scores_higher_than_more_decay(analyzer):
    """The original ADDED theta.abs(), rewarding the fastest decay."""
    df = frame([option(theta=-0.45), option(theta=-0.05)])
    result = analyzer.analyze_options(df, PASSING_IV)
    assert result.iloc[0]["theta"] == -0.05


def test_unavailable_iv_blocks_the_symbol(analyzer):
    """A failed IV lookup must not look like a passing 50th percentile."""
    result = analyzer.analyze_options(frame([option()]), {"iv_unavailable": True})
    assert result.empty


def test_iv_outside_the_window_blocks_the_symbol(analyzer):
    assert analyzer.analyze_options(frame([option()]), {"iv_percentile": 85}).empty


def test_iv_inside_the_window_allows_signals(analyzer):
    assert not analyzer.analyze_options(frame([option()]), {"iv_percentile": 45}).empty


def test_empty_input_returns_empty(analyzer):
    assert analyzer.analyze_options(pd.DataFrame(), PASSING_IV).empty


def test_identical_options_do_not_produce_nan_scores(analyzer):
    """Zero spread in a normalised term must not divide by zero."""
    result = analyzer.analyze_options(frame([option(), option()]), PASSING_IV)
    assert result["breakout_score"].notna().all()
