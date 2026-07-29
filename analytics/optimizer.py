"""Portfolio optimizers: MPT, Risk Parity, simple Black-Litterman blend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from config.settings import settings


@dataclass
class OptimizationResult:
    method: str
    weights: dict[str, float]
    expected_return: float
    expected_risk: float
    sharpe: float
    efficient_frontier: list[dict[str, float]] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PortfolioOptimizer:
    """Mean-variance and risk-parity optimizers for fund return series."""

    def __init__(self, risk_free_rate: Optional[float] = None) -> None:
        self.rf = risk_free_rate if risk_free_rate is not None else settings.risk_free_rate
        self.td = settings.trading_days_per_year

    def _prep(self, returns: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]:
        r = returns.dropna(how="any")
        cols = list(r.columns)
        mu = r.mean().values * self.td
        cov = r.cov().values * self.td
        # Regularize
        cov = cov + np.eye(len(cols)) * 1e-8
        return mu, cov, cols

    def max_sharpe(self, returns: pd.DataFrame) -> OptimizationResult:
        mu, cov, cols = self._prep(returns)
        n = len(cols)
        if n == 0:
            return OptimizationResult("max_sharpe", {}, 0, 0, 0, notes="No data")

        def neg_sharpe(w: np.ndarray) -> float:
            ret = float(w @ mu)
            vol = float(np.sqrt(w @ cov @ w))
            if vol <= 0:
                return 1e6
            return -(ret - self.rf) / vol

        cons = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
        bounds = tuple((0.0, 1.0) for _ in range(n))
        w0 = np.ones(n) / n
        res = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=cons)
        w = res.x if res.success else w0
        return self._result("max_sharpe", w, mu, cov, cols, self._frontier(mu, cov, cols))

    def min_variance(self, returns: pd.DataFrame) -> OptimizationResult:
        mu, cov, cols = self._prep(returns)
        n = len(cols)
        if n == 0:
            return OptimizationResult("min_variance", {}, 0, 0, 0, notes="No data")

        def port_var(w: np.ndarray) -> float:
            return float(w @ cov @ w)

        cons = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
        bounds = tuple((0.0, 1.0) for _ in range(n))
        w0 = np.ones(n) / n
        res = minimize(port_var, w0, method="SLSQP", bounds=bounds, constraints=cons)
        w = res.x if res.success else w0
        return self._result("min_variance", w, mu, cov, cols, self._frontier(mu, cov, cols))

    def risk_parity(self, returns: pd.DataFrame) -> OptimizationResult:
        mu, cov, cols = self._prep(returns)
        n = len(cols)
        if n == 0:
            return OptimizationResult("risk_parity", {}, 0, 0, 0, notes="No data")

        def rp_objective(w: np.ndarray) -> float:
            w = np.maximum(w, 1e-8)
            port_var = float(w @ cov @ w)
            mrc = cov @ w
            rc = w * mrc
            target = port_var / n
            return float(np.sum((rc - target) ** 2))

        cons = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
        bounds = tuple((0.01, 1.0) for _ in range(n))
        w0 = np.ones(n) / n
        res = minimize(rp_objective, w0, method="SLSQP", bounds=bounds, constraints=cons)
        w = res.x if res.success else w0
        w = w / w.sum()
        return self._result("risk_parity", w, mu, cov, cols)

    def black_litterman_simple(
        self,
        returns: pd.DataFrame,
        views: Optional[dict[str, float]] = None,
        view_confidence: float = 0.25,
    ) -> OptimizationResult:
        """
        Simplified Black-Litterman: blend market-implied (equal) prior with absolute views.

        views: {asset: expected annual return}, e.g. {"Fund A": 0.14}
        """
        mu, cov, cols = self._prep(returns)
        n = len(cols)
        if n == 0:
            return OptimizationResult("black_litterman", {}, 0, 0, 0, notes="No data")

        # Prior = historical mean shrink to equal
        prior = 0.7 * mu + 0.3 * np.mean(mu)
        if views:
            for i, c in enumerate(cols):
                if c in views:
                    prior[i] = (1 - view_confidence) * prior[i] + view_confidence * views[c]

        def neg_sharpe(w: np.ndarray) -> float:
            ret = float(w @ prior)
            vol = float(np.sqrt(w @ cov @ w))
            return -((ret - self.rf) / vol) if vol > 0 else 1e6

        cons = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
        bounds = tuple((0.0, 1.0) for _ in range(n))
        w0 = np.ones(n) / n
        res = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=cons)
        w = res.x if res.success else w0
        result = self._result("black_litterman", w, prior, cov, cols)
        result.notes = "Simplified BL blend of historical means with optional absolute views."
        return result

    def equal_weight(self, returns: pd.DataFrame) -> OptimizationResult:
        mu, cov, cols = self._prep(returns)
        n = len(cols)
        w = np.ones(n) / n if n else np.array([])
        return self._result("equal_weight", w, mu, cov, cols)

    def _frontier(
        self, mu: np.ndarray, cov: np.ndarray, cols: list[str], points: int = 25
    ) -> list[dict[str, float]]:
        n = len(cols)
        if n < 2:
            return []
        target_rets = np.linspace(mu.min(), mu.max(), points)
        frontier = []
        for tr in target_rets:
            cons = (
                {"type": "eq", "fun": lambda w: np.sum(w) - 1},
                {"type": "eq", "fun": lambda w, t=tr: float(w @ mu) - t},
            )
            bounds = tuple((0.0, 1.0) for _ in range(n))
            w0 = np.ones(n) / n

            def port_var(w: np.ndarray) -> float:
                return float(w @ cov @ w)

            res = minimize(port_var, w0, method="SLSQP", bounds=bounds, constraints=cons)
            if res.success:
                w = res.x
                vol = float(np.sqrt(w @ cov @ w))
                ret = float(w @ mu)
                frontier.append({"risk": round(vol, 4), "return": round(ret, 4)})
        return frontier

    def _result(
        self,
        method: str,
        w: np.ndarray,
        mu: np.ndarray,
        cov: np.ndarray,
        cols: list[str],
        frontier: Optional[list] = None,
    ) -> OptimizationResult:
        if len(w) == 0:
            return OptimizationResult(method, {}, 0, 0, 0)
        w = np.maximum(w, 0)
        w = w / w.sum()
        ret = float(w @ mu)
        risk = float(np.sqrt(w @ cov @ w))
        sharpe = (ret - self.rf) / risk if risk > 0 else 0.0
        weights = {c: round(float(wi), 4) for c, wi in zip(cols, w)}
        return OptimizationResult(
            method=method,
            weights=weights,
            expected_return=round(ret, 4),
            expected_risk=round(risk, 4),
            sharpe=round(sharpe, 3),
            efficient_frontier=frontier or [],
        )
