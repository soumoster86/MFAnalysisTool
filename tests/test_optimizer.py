"""Tests for portfolio optimizer."""

import numpy as np
import pandas as pd

from analytics.optimizer import PortfolioOptimizer


def test_max_sharpe_weights_sum_to_one() -> None:
    rng = np.random.default_rng(1)
    rets = pd.DataFrame(
        rng.normal(0.0005, 0.01, size=(400, 3)),
        columns=["A", "B", "C"],
    )
    res = PortfolioOptimizer().max_sharpe(rets)
    assert abs(sum(res.weights.values()) - 1.0) < 1e-3
    assert res.expected_risk >= 0


def test_risk_parity() -> None:
    rng = np.random.default_rng(2)
    rets = pd.DataFrame(rng.normal(0.0004, 0.012, size=(300, 4)), columns=list("WXYZ"))
    res = PortfolioOptimizer().risk_parity(rets)
    assert abs(sum(res.weights.values()) - 1.0) < 1e-3
