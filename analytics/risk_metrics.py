"""Risk and return metrics for mutual funds and portfolios."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import settings
from utils.helpers import safe_div


@dataclass
class RiskMetrics:
    """Container for standard risk/return statistics."""

    cagr: Optional[float] = None
    total_return: Optional[float] = None
    volatility: Optional[float] = None
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    max_drawdown: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    treynor: Optional[float] = None
    information_ratio: Optional[float] = None
    upside_capture: Optional[float] = None
    downside_capture: Optional[float] = None
    capture_ratio: Optional[float] = None
    calmar: Optional[float] = None
    var_95: Optional[float] = None
    cvar_95: Optional[float] = None
    rolling_return_1y: Optional[float] = None
    rolling_return_3y: Optional[float] = None
    n_obs: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class RiskMetricsCalculator:
    """Compute classical quant metrics from NAV or return series."""

    def __init__(
        self,
        risk_free_rate: Optional[float] = None,
        trading_days: Optional[int] = None,
    ) -> None:
        self.rf = risk_free_rate if risk_free_rate is not None else settings.risk_free_rate
        self.td = trading_days if trading_days is not None else settings.trading_days_per_year

    def nav_to_returns(self, nav: pd.Series) -> pd.Series:
        """Convert NAV series to simple daily returns."""
        s = nav.dropna().astype(float).sort_index()
        return s.pct_change().dropna()

    def cagr_from_nav(self, nav: pd.Series) -> Optional[float]:
        s = nav.dropna().astype(float).sort_index()
        if len(s) < 2:
            return None
        start, end = float(s.iloc[0]), float(s.iloc[-1])
        if start <= 0 or end <= 0:
            return None
        # Prefer datetime index if available
        if isinstance(s.index, pd.DatetimeIndex):
            years = max((s.index[-1] - s.index[0]).days / 365.25, 1 / 365.25)
        else:
            years = max(len(s) / self.td, 1 / self.td)
        return (end / start) ** (1 / years) - 1

    def max_drawdown(self, nav: pd.Series) -> float:
        s = nav.dropna().astype(float).sort_index()
        if s.empty:
            return 0.0
        peak = s.cummax()
        dd = (s - peak) / peak
        return float(dd.min())

    def drawdown_series(self, nav: pd.Series) -> pd.Series:
        s = nav.dropna().astype(float).sort_index()
        peak = s.cummax()
        return (s - peak) / peak

    def annualized_vol(self, returns: pd.Series) -> float:
        r = returns.dropna()
        if len(r) < 2:
            return 0.0
        return float(r.std(ddof=1) * np.sqrt(self.td))

    def sharpe_ratio(self, returns: pd.Series) -> Optional[float]:
        r = returns.dropna()
        if len(r) < 2:
            return None
        excess = r.mean() * self.td - self.rf
        vol = self.annualized_vol(r)
        return safe_div(excess, vol, default=None)  # type: ignore[return-value]

    def sortino_ratio(self, returns: pd.Series) -> Optional[float]:
        r = returns.dropna()
        if len(r) < 2:
            return None
        downside = r[r < 0]
        if len(downside) < 1:
            return None
        downside_std = float(downside.std(ddof=1) * np.sqrt(self.td))
        excess = r.mean() * self.td - self.rf
        return safe_div(excess, downside_std, default=None)  # type: ignore[return-value]

    def beta_alpha(
        self, returns: pd.Series, benchmark: pd.Series
    ) -> tuple[Optional[float], Optional[float]]:
        aligned = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
        if len(aligned) < 20:
            return None, None
        y = aligned.iloc[:, 0].values
        x = aligned.iloc[:, 1].values
        var_x = np.var(x, ddof=1)
        if var_x == 0:
            return None, None
        cov = np.cov(y, x, ddof=1)[0, 1]
        beta = cov / var_x
        alpha_daily = y.mean() - beta * x.mean()
        alpha_ann = (1 + alpha_daily) ** self.td - 1
        return float(beta), float(alpha_ann)

    def treynor(self, returns: pd.Series, beta: Optional[float]) -> Optional[float]:
        if beta is None or beta == 0:
            return None
        r = returns.dropna()
        if r.empty:
            return None
        excess = r.mean() * self.td - self.rf
        return excess / beta

    def information_ratio(
        self, returns: pd.Series, benchmark: pd.Series
    ) -> Optional[float]:
        aligned = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
        if len(aligned) < 20:
            return None
        active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
        te = float(active.std(ddof=1) * np.sqrt(self.td))
        active_ret = float(active.mean() * self.td)
        return safe_div(active_ret, te, default=None)  # type: ignore[return-value]

    def capture_ratios(
        self, returns: pd.Series, benchmark: pd.Series
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        aligned = pd.concat(
            [returns.rename("f"), benchmark.rename("b")], axis=1, join="inner"
        ).dropna()
        if len(aligned) < 20:
            return None, None, None
        up = aligned[aligned["b"] > 0]
        down = aligned[aligned["b"] < 0]
        up_cap = (
            safe_div(up["f"].mean(), up["b"].mean(), default=None) if len(up) else None
        )
        down_cap = (
            safe_div(down["f"].mean(), down["b"].mean(), default=None)
            if len(down)
            else None
        )
        if up_cap is not None and down_cap is not None and down_cap != 0:
            cap_ratio = up_cap / abs(down_cap) if down_cap != 0 else None
        else:
            cap_ratio = None
        return (
            float(up_cap) if up_cap is not None else None,
            float(down_cap) if down_cap is not None else None,
            float(cap_ratio) if cap_ratio is not None else None,
        )

    def var_cvar(self, returns: pd.Series, level: float = 0.05) -> tuple[float, float]:
        r = returns.dropna()
        if r.empty:
            return 0.0, 0.0
        var = float(np.quantile(r, level))
        cvar = float(r[r <= var].mean()) if (r <= var).any() else var
        return var, cvar

    def rolling_return(self, nav: pd.Series, window_days: int = 252) -> Optional[float]:
        s = nav.dropna().astype(float).sort_index()
        if len(s) < window_days + 1:
            return None
        start, end = float(s.iloc[-window_days - 1]), float(s.iloc[-1])
        if start <= 0:
            return None
        years = window_days / self.td
        return (end / start) ** (1 / years) - 1

    def compute(
        self,
        nav: pd.Series,
        benchmark_nav: Optional[pd.Series] = None,
    ) -> RiskMetrics:
        """Full metrics suite from fund NAV (and optional benchmark NAV)."""
        nav = nav.dropna().astype(float).sort_index()
        rets = self.nav_to_returns(nav)
        metrics = RiskMetrics(n_obs=len(rets))
        if rets.empty:
            return metrics

        metrics.cagr = self.cagr_from_nav(nav)
        metrics.total_return = float(nav.iloc[-1] / nav.iloc[0] - 1) if len(nav) > 1 else None
        metrics.volatility = self.annualized_vol(rets)
        metrics.sharpe = self.sharpe_ratio(rets)
        metrics.sortino = self.sortino_ratio(rets)
        metrics.max_drawdown = self.max_drawdown(nav)
        metrics.calmar = (
            safe_div(metrics.cagr or 0, abs(metrics.max_drawdown), default=None)
            if metrics.max_drawdown
            else None
        )
        metrics.var_95, metrics.cvar_95 = self.var_cvar(rets)
        metrics.rolling_return_1y = self.rolling_return(nav, self.td)
        metrics.rolling_return_3y = self.rolling_return(nav, self.td * 3)

        if benchmark_nav is not None and not benchmark_nav.dropna().empty:
            b_nav = benchmark_nav.dropna().astype(float).sort_index()
            b_rets = self.nav_to_returns(b_nav)
            beta, alpha = self.beta_alpha(rets, b_rets)
            metrics.beta = beta
            metrics.alpha = alpha
            metrics.treynor = self.treynor(rets, beta)
            metrics.information_ratio = self.information_ratio(rets, b_rets)
            up, down, cap = self.capture_ratios(rets, b_rets)
            metrics.upside_capture = up
            metrics.downside_capture = down
            metrics.capture_ratio = cap

        return metrics

    def correlation_matrix(self, returns_df: pd.DataFrame) -> pd.DataFrame:
        """Pairwise correlation of return columns."""
        return returns_df.dropna(how="all").corr()
