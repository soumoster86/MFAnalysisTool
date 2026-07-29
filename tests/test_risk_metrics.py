"""Unit tests for risk metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.risk_metrics import RiskMetricsCalculator


@pytest.fixture
def nav_series() -> pd.Series:
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2020-01-01", periods=500)
    rets = rng.normal(0.0004, 0.01, size=500)
    prices = 100 * np.cumprod(1 + rets)
    return pd.Series(prices, index=dates, name="fund")


def test_cagr_positive(nav_series: pd.Series) -> None:
    calc = RiskMetricsCalculator()
    cagr = calc.cagr_from_nav(nav_series)
    assert cagr is not None
    assert -0.5 < cagr < 1.0


def test_max_drawdown_non_positive(nav_series: pd.Series) -> None:
    calc = RiskMetricsCalculator()
    dd = calc.max_drawdown(nav_series)
    assert dd <= 0


def test_full_metrics(nav_series: pd.Series) -> None:
    calc = RiskMetricsCalculator()
    bench = nav_series * 1.01
    m = calc.compute(nav_series, bench)
    assert m.n_obs > 0
    assert m.volatility is not None and m.volatility > 0
    assert m.sharpe is not None
    assert m.beta is not None


def test_empty_nav() -> None:
    calc = RiskMetricsCalculator()
    m = calc.compute(pd.Series(dtype=float))
    assert m.n_obs == 0
