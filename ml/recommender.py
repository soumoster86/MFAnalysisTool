"""Rule + score based fund recommendation engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import pandas as pd

from analytics.health_score import FundHealthScorer
from analytics.optimizer import PortfolioOptimizer
from analytics.risk_metrics import RiskMetricsCalculator
from services.data.fund_service import FundService


@dataclass
class RecommendationResult:
    risk_appetite: str
    horizon_years: int
    recommended_funds: list[dict[str, Any]] = field(default_factory=list)
    allocation: dict[str, float] = field(default_factory=dict)
    expected_return: Optional[float] = None
    expected_risk: Optional[float] = None
    risk_analysis: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecommendationEngine:
    """Map risk profile → category mix → ranked funds → allocation."""

    PROFILE_MIX = {
        "Conservative": {"Debt": 0.55, "Hybrid": 0.25, "Equity": 0.15, "Index/ETF": 0.05},
        "Moderate": {"Debt": 0.25, "Hybrid": 0.20, "Equity": 0.45, "Index/ETF": 0.10},
        "Aggressive": {"Debt": 0.05, "Hybrid": 0.10, "Equity": 0.70, "Index/ETF": 0.15},
        "Very Aggressive": {"Debt": 0.0, "Hybrid": 0.05, "Equity": 0.80, "Index/ETF": 0.15},
    }

    def __init__(self, fund_service: Optional[FundService] = None) -> None:
        self.funds = fund_service or FundService()
        self.scorer = FundHealthScorer()
        self.risk = RiskMetricsCalculator()
        self.optimizer = PortfolioOptimizer()

    def recommend(
        self,
        *,
        risk_appetite: str = "Moderate",
        investment_horizon: int = 7,
        monthly_sip: float = 10000,
        age: int = 30,
        goals: Optional[str] = None,
        max_funds: int = 5,
    ) -> RecommendationResult:
        risk_appetite = risk_appetite if risk_appetite in self.PROFILE_MIX else "Moderate"
        mix = dict(self.PROFILE_MIX[risk_appetite])

        # Horizon tilt
        if investment_horizon >= 10:
            mix["Equity"] = mix.get("Equity", 0) + 0.05
            mix["Debt"] = max(0, mix.get("Debt", 0) - 0.05)
        elif investment_horizon <= 3:
            mix["Debt"] = mix.get("Debt", 0) + 0.10
            mix["Equity"] = max(0, mix.get("Equity", 0) - 0.10)

        # Age tilt
        if age >= 50:
            mix["Debt"] = mix.get("Debt", 0) + 0.10
            mix["Equity"] = max(0, mix.get("Equity", 0) - 0.10)

        # Normalize
        total = sum(mix.values()) or 1
        mix = {k: v / total for k, v in mix.items() if v > 0}

        try:
            universe = self.funds.search_funds(limit=200, direct_growth_only=True)
        except Exception:
            universe = pd.DataFrame()

        picked: list[dict[str, Any]] = []
        allocation: dict[str, float] = {}

        if universe.empty:
            return RecommendationResult(
                risk_appetite=risk_appetite,
                horizon_years=investment_horizon,
                risk_analysis="Could not load fund universe.",
                notes=["Refresh AMFI data and retry."],
            )

        for cat, weight in sorted(mix.items(), key=lambda x: -x[1]):
            if weight <= 0:
                continue
            subset = universe[universe["category"] == cat]
            if subset.empty:
                subset = universe
            # Take a few candidates and score lightly
            n_take = max(1, int(round(weight * max_funds)))
            candidates = subset.head(n_take * 3)
            scored = []
            for _, row in candidates.iterrows():
                try:
                    analytics = self.funds.compute_fund_analytics(str(row["amfi_code"]))
                    h = analytics["health"]["overall"]
                    scored.append((h, row, analytics))
                except Exception:
                    scored.append((50.0, row, None))
            scored.sort(key=lambda x: -x[0])
            for h, row, analytics in scored[:n_take]:
                if len(picked) >= max_funds:
                    break
                name = row["scheme_name"]
                if any(p["scheme_name"] == name for p in picked):
                    continue
                share = weight / n_take
                picked.append(
                    {
                        "amfi_code": str(row["amfi_code"]),
                        "scheme_name": name,
                        "category": row.get("category"),
                        "subcategory": row.get("subcategory"),
                        "health_score": h,
                        "suggested_weight_pct": round(share * 100, 1),
                        "nav": row.get("nav"),
                        "metrics": (analytics or {}).get("metrics"),
                    }
                )
                allocation[name] = round(share, 4)

        # Renormalize allocation
        s = sum(allocation.values()) or 1
        allocation = {k: round(v / s, 4) for k, v in allocation.items()}
        for p in picked:
            p["suggested_weight_pct"] = round(allocation.get(p["scheme_name"], 0) * 100, 1)

        # Expected risk/return blend from health metrics when available
        exp_ret = 0.0
        exp_risk = 0.0
        wsum = 0.0
        for p in picked:
            w = allocation.get(p["scheme_name"], 0)
            m = p.get("metrics") or {}
            r = m.get("cagr") if m.get("cagr") is not None else 0.10
            v = m.get("volatility") if m.get("volatility") is not None else 0.15
            exp_ret += w * float(r)
            exp_risk += w * float(v)
            wsum += w
        if wsum:
            exp_ret /= 1
            exp_risk /= 1

        analysis = (
            f"{risk_appetite} profile, {investment_horizon}y horizon, age {age}. "
            f"Category mix targets: " + ", ".join(f"{k} {v:.0%}" for k, v in mix.items()) + ". "
            f"Monthly SIP ₹{monthly_sip:,.0f} can be split by suggested weights."
        )
        if goals:
            analysis += f" Goal context: {goals}."

        notes = [
            "Recommendations use live AMFI universe + model-based health scores.",
            "NAV history is reconstructed for Phase 1 analytics; validate before investing.",
            "Not investment advice — educational tool only.",
        ]

        return RecommendationResult(
            risk_appetite=risk_appetite,
            horizon_years=investment_horizon,
            recommended_funds=picked,
            allocation=allocation,
            expected_return=round(exp_ret, 4),
            expected_risk=round(exp_risk, 4),
            risk_analysis=analysis,
            notes=notes,
        )
