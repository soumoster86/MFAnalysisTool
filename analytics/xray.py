"""Mutual Fund X-Ray: deep single-fund diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import pandas as pd

from analytics.health_score import FundHealthScorer, HealthScoreBreakdown
from analytics.risk_metrics import RiskMetrics, RiskMetricsCalculator


@dataclass
class XRayReport:
    scheme_name: str
    overall_health: HealthScoreBreakdown
    risk_metrics: dict[str, Any]
    hidden_risks: list[str] = field(default_factory=list)
    style_drift: Optional[str] = None
    sector_bias: dict[str, float] = field(default_factory=dict)
    market_cap_bias: dict[str, float] = field(default_factory=dict)
    country_bias: dict[str, float] = field(default_factory=dict)
    hidden_concentration: list[dict[str, Any]] = field(default_factory=list)
    manager_dependency: str = ""
    expense_analysis: str = ""
    historical_stability: str = ""
    benchmark_comparison: str = ""
    suggested_alternatives: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class FundXRay:
    """Generate a Morningstar-style X-Ray for a single fund."""

    def __init__(self) -> None:
        self.risk = RiskMetricsCalculator()
        self.scorer = FundHealthScorer()

    def analyze(
        self,
        *,
        scheme_name: str,
        nav: pd.Series,
        holdings: Optional[pd.DataFrame] = None,
        benchmark_nav: Optional[pd.Series] = None,
        expense_ratio: Optional[float] = None,
        fund_manager: Optional[str] = None,
        manager_tenure: Optional[float] = None,
        aum_cr: Optional[float] = None,
        category: Optional[str] = None,
        riskometer: Optional[str] = None,
    ) -> XRayReport:
        metrics: RiskMetrics = self.risk.compute(nav, benchmark_nav)

        top10 = None
        n_hold = None
        sector_bias: dict[str, float] = {}
        mcap_bias: dict[str, float] = {}
        country_bias: dict[str, float] = {}
        concentration: list[dict[str, Any]] = []

        if holdings is not None and not holdings.empty:
            wt_col = self._col(holdings, ["weight_pct", "weight", "pct"])
            sec_col = self._col(holdings, ["security_name", "name", "stock"])
            sector_col = self._col(holdings, ["sector"])
            mcap_col = self._col(holdings, ["market_cap", "mcap"])
            country_col = self._col(holdings, ["country"])
            if wt_col:
                w = holdings[wt_col].astype(float)
                if w.max() <= 1:
                    w = w * 100
                n_hold = len(holdings)
                top10 = float(w.nlargest(min(10, len(w))).sum())
                if sec_col:
                    tmp = holdings.assign(_w=w)
                    concentration = (
                        tmp.nlargest(5, "_w")[[sec_col, "_w"]]
                        .rename(columns={sec_col: "security", "_w": "weight_pct"})
                        .to_dict("records")
                    )
                if sector_col:
                    sector_bias = (
                        holdings.assign(_w=w).groupby(sector_col)["_w"].sum().sort_values(ascending=False).round(2).to_dict()
                    )
                if mcap_col:
                    mcap_bias = (
                        holdings.assign(_w=w).groupby(mcap_col)["_w"].sum().sort_values(ascending=False).round(2).to_dict()
                    )
                if country_col:
                    country_bias = (
                        holdings.assign(_w=w).groupby(country_col)["_w"].sum().sort_values(ascending=False).round(2).to_dict()
                    )

        health = self.scorer.score(
            cagr=metrics.cagr,
            sharpe=metrics.sharpe,
            sortino=metrics.sortino,
            max_drawdown=metrics.max_drawdown,
            volatility=metrics.volatility,
            alpha=metrics.alpha,
            beta=metrics.beta,
            information_ratio=metrics.information_ratio,
            expense_ratio=expense_ratio,
            aum_cr=aum_cr,
            manager_tenure_years=manager_tenure,
            top10_concentration=top10,
            n_holdings=n_hold,
        )

        hidden: list[str] = []
        if metrics.max_drawdown is not None and metrics.max_drawdown < -0.35:
            hidden.append(f"Severe historical drawdown of {metrics.max_drawdown:.1%}.")
        if metrics.beta is not None and metrics.beta > 1.2:
            hidden.append(f"Elevated market sensitivity (beta={metrics.beta:.2f}).")
        if top10 is not None and top10 > 55:
            hidden.append(f"High top-10 concentration ({top10:.1f}%).")
        if expense_ratio is not None and expense_ratio > 1.5:
            hidden.append(f"Elevated expense ratio ({expense_ratio:.2f}%).")
        if metrics.volatility is not None and metrics.volatility > 0.22:
            hidden.append(f"High annualized volatility ({metrics.volatility:.1%}).")
        if not hidden:
            hidden.append("No major hidden red flags from available data.")

        style = None
        if mcap_bias:
            dominant = max(mcap_bias, key=mcap_bias.get)  # type: ignore[arg-type]
            style = f"Style appears tilted to {dominant} ({mcap_bias[dominant]:.0f}% of equity book)."
        elif category:
            style = f"Declared category: {category}. Holdings-based style confirmation limited."

        mgr = "Unknown manager dependency."
        if fund_manager:
            tenure_txt = f" (~{manager_tenure:.1f}y tenure)" if manager_tenure else ""
            if manager_tenure is not None and manager_tenure < 2:
                mgr = f"High manager dependency risk: {fund_manager}{tenure_txt} — short tenure."
            elif manager_tenure is not None and manager_tenure >= 5:
                mgr = f"Stable management: {fund_manager}{tenure_txt}."
            else:
                mgr = f"Managed by {fund_manager}{tenure_txt}."

        if expense_ratio is None:
            exp = "Expense ratio not available."
        elif expense_ratio <= 0.5:
            exp = f"Cost-efficient at {expense_ratio:.2f}% TER — competitive for active/index hybrid."
        elif expense_ratio <= 1.0:
            exp = f"Moderate TER {expense_ratio:.2f}% — acceptable if alpha persists."
        else:
            exp = f"High TER {expense_ratio:.2f}% — requires sustained outperformance to justify."

        stability = "Insufficient history."
        if metrics.sharpe is not None and metrics.max_drawdown is not None:
            if (metrics.sharpe or 0) > 0.8 and (metrics.max_drawdown or 0) > -0.25:
                stability = "Historically stable risk-adjusted profile."
            elif (metrics.max_drawdown or 0) < -0.4:
                stability = "History shows deep drawdowns — path dependency risk for new SIPs."
            else:
                stability = "Mixed stability — typical for the risk category."

        bench = "No benchmark series supplied."
        if metrics.alpha is not None:
            bench = (
                f"Alpha≈{metrics.alpha:.2%}, Beta≈{metrics.beta or float('nan'):.2f}, "
                f"Info Ratio≈{metrics.information_ratio or float('nan'):.2f}."
            )

        alts = [
            "Low-cost category index fund (if active edge is unclear)",
            "Peer flexi-cap / large-cap with lower overlap and TER",
            "International feeder for geographic diversification",
        ]

        summary = (
            f"{scheme_name}: Health {health.overall}/100. {health.narrative} "
            f"Riskometer: {riskometer or 'N/A'}. AUM: {aum_cr or 'N/A'} Cr."
        )

        return XRayReport(
            scheme_name=scheme_name,
            overall_health=health,
            risk_metrics=metrics.to_dict(),
            hidden_risks=hidden,
            style_drift=style,
            sector_bias=sector_bias,
            market_cap_bias=mcap_bias,
            country_bias=country_bias,
            hidden_concentration=concentration,
            manager_dependency=mgr,
            expense_analysis=exp,
            historical_stability=stability,
            benchmark_comparison=bench,
            suggested_alternatives=alts,
            summary=summary,
        )

    @staticmethod
    def _col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        lower = {c.lower(): c for c in df.columns}
        for c in candidates:
            if c.lower() in lower:
                return lower[c.lower()]
        return None
