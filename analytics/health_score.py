"""Fund Health Score engine (0–100 multi-factor model)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from utils.helpers import clamp


@dataclass
class HealthScoreBreakdown:
    """Multi-dimensional fund health scores."""

    overall: float = 0.0
    growth: float = 50.0
    risk: float = 50.0
    quality: float = 50.0
    cost_efficiency: float = 50.0
    consistency: float = 50.0
    diversification: float = 50.0
    factors: dict[str, float] = field(default_factory=dict)
    narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FundHealthScorer:
    """
    Score a fund 0–100 using transparent, calculation-backed heuristics.

    Designed to work with partial data: missing factors are neutral (50)
    and down-weighted in the overall blend.
    """

    WEIGHTS = {
        "growth": 0.22,
        "risk": 0.20,
        "quality": 0.18,
        "cost_efficiency": 0.12,
        "consistency": 0.16,
        "diversification": 0.12,
    }

    def score(
        self,
        *,
        cagr: Optional[float] = None,
        sharpe: Optional[float] = None,
        sortino: Optional[float] = None,
        max_drawdown: Optional[float] = None,
        volatility: Optional[float] = None,
        alpha: Optional[float] = None,
        beta: Optional[float] = None,
        information_ratio: Optional[float] = None,
        expense_ratio: Optional[float] = None,
        aum_cr: Optional[float] = None,
        manager_tenure_years: Optional[float] = None,
        top10_concentration: Optional[float] = None,
        n_holdings: Optional[int] = None,
        category_avg_cagr: Optional[float] = None,
        rolling_consistency: Optional[float] = None,
    ) -> HealthScoreBreakdown:
        factors: dict[str, float] = {}

        # --- Growth ---
        growth_parts: list[float] = []
        if cagr is not None:
            # Map CAGR ~0% → 30, 12% → 70, 20%+ → 95
            g = clamp(30 + (cagr * 100) * 3.5, 5, 98)
            growth_parts.append(g)
            factors["cagr"] = g
        if alpha is not None:
            a = clamp(50 + alpha * 100 * 4, 5, 98)
            growth_parts.append(a)
            factors["alpha"] = a
        if category_avg_cagr is not None and cagr is not None:
            rel = clamp(50 + (cagr - category_avg_cagr) * 100 * 5, 5, 98)
            growth_parts.append(rel)
            factors["relative_cagr"] = rel
        growth = sum(growth_parts) / len(growth_parts) if growth_parts else 50.0

        # --- Risk (higher score = better risk profile) ---
        risk_parts: list[float] = []
        if max_drawdown is not None:
            # -10% DD → ~80, -40% → ~20
            r = clamp(100 + max_drawdown * 200, 5, 98)  # max_drawdown negative
            risk_parts.append(r)
            factors["max_drawdown"] = r
        if volatility is not None:
            # 10% vol → 80, 25% → 40
            r = clamp(100 - volatility * 100 * 2.5, 5, 98)
            risk_parts.append(r)
            factors["volatility"] = r
        if beta is not None:
            # beta 1.0 → 55, 0.8 → 70, 1.4 → 30
            r = clamp(55 + (1.0 - beta) * 50, 5, 98)
            risk_parts.append(r)
            factors["beta"] = r
        if sharpe is not None:
            r = clamp(40 + sharpe * 25, 5, 98)
            risk_parts.append(r)
            factors["sharpe"] = r
        risk = sum(risk_parts) / len(risk_parts) if risk_parts else 50.0

        # --- Quality ---
        quality_parts: list[float] = []
        if manager_tenure_years is not None:
            q = clamp(30 + manager_tenure_years * 8, 10, 95)
            quality_parts.append(q)
            factors["manager_tenure"] = q
        if aum_cr is not None:
            # Sweet spot 500–15000 Cr
            if aum_cr < 100:
                q = 35
            elif aum_cr < 500:
                q = 55
            elif aum_cr < 15000:
                q = 80
            elif aum_cr < 50000:
                q = 65
            else:
                q = 50
            quality_parts.append(float(q))
            factors["aum"] = float(q)
        if information_ratio is not None:
            q = clamp(50 + information_ratio * 30, 5, 98)
            quality_parts.append(q)
            factors["information_ratio"] = q
        quality = sum(quality_parts) / len(quality_parts) if quality_parts else 50.0

        # --- Cost ---
        if expense_ratio is not None:
            # 0.3% → 90, 1.0% → 55, 2.0% → 25
            cost = clamp(100 - expense_ratio * 40, 10, 98)
            factors["expense_ratio"] = cost
        else:
            cost = 50.0

        # --- Consistency ---
        consistency_parts: list[float] = []
        if sortino is not None:
            c = clamp(40 + sortino * 22, 5, 98)
            consistency_parts.append(c)
            factors["sortino"] = c
        if rolling_consistency is not None:
            consistency_parts.append(clamp(rolling_consistency, 5, 98))
            factors["rolling_consistency"] = clamp(rolling_consistency, 5, 98)
        consistency = (
            sum(consistency_parts) / len(consistency_parts) if consistency_parts else 50.0
        )

        # --- Diversification ---
        div_parts: list[float] = []
        if top10_concentration is not None:
            # 30% top10 → 85, 60% → 40
            d = clamp(100 - top10_concentration * 1.2, 10, 95)
            div_parts.append(d)
            factors["top10_concentration"] = d
        if n_holdings is not None:
            if n_holdings < 15:
                d = 30
            elif n_holdings < 30:
                d = 55
            elif n_holdings < 60:
                d = 80
            else:
                d = 70
            div_parts.append(float(d))
            factors["n_holdings"] = float(d)
        diversification = sum(div_parts) / len(div_parts) if div_parts else 50.0

        dims = {
            "growth": growth,
            "risk": risk,
            "quality": quality,
            "cost_efficiency": cost,
            "consistency": consistency,
            "diversification": diversification,
        }
        overall = sum(dims[k] * self.WEIGHTS[k] for k in self.WEIGHTS)
        overall = clamp(overall, 0, 100)

        narrative = self._narrative(overall, dims)

        return HealthScoreBreakdown(
            overall=round(overall, 1),
            growth=round(growth, 1),
            risk=round(risk, 1),
            quality=round(quality, 1),
            cost_efficiency=round(cost, 1),
            consistency=round(consistency, 1),
            diversification=round(diversification, 1),
            factors={k: round(v, 1) for k, v in factors.items()},
            narrative=narrative,
        )

    def _narrative(self, overall: float, dims: dict[str, float]) -> str:
        if overall >= 80:
            tier = "Excellent"
        elif overall >= 65:
            tier = "Good"
        elif overall >= 50:
            tier = "Average"
        elif overall >= 35:
            tier = "Below Average"
        else:
            tier = "Weak"

        best = max(dims, key=dims.get)  # type: ignore[arg-type]
        worst = min(dims, key=dims.get)  # type: ignore[arg-type]
        return (
            f"{tier} fund health ({overall:.0f}/100). "
            f"Strongest pillar: {best.replace('_', ' ')} ({dims[best]:.0f}). "
            f"Weakest pillar: {worst.replace('_', ' ')} ({dims[worst]:.0f})."
        )
