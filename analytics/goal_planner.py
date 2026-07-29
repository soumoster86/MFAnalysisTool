"""Goal-based planning with Monte Carlo simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class GoalPlanResult:
    years: float
    expected_corpus: float
    required_sip: float
    required_return: Optional[float]
    probability_of_success: float
    worst_case: float
    average_case: float
    best_case: float
    percentiles: dict[str, float] = field(default_factory=dict)
    monthly_path_median: list[float] = field(default_factory=list)
    simulation_paths_sample: list[list[float]] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GoalPlanner:
    """Retirement / goal corpus planner with Monte Carlo."""

    def plan(
        self,
        *,
        age: int,
        retirement_age: int,
        current_investment: float,
        monthly_sip: float,
        expected_return: float,
        expected_inflation: float = 0.06,
        goal_amount: Optional[float] = None,
        return_volatility: float = 0.12,
        n_simulations: int = 2000,
        seed: int = 42,
    ) -> GoalPlanResult:
        years = max(retirement_age - age, 0)
        months = int(years * 12)
        if months <= 0:
            return GoalPlanResult(
                years=0,
                expected_corpus=current_investment,
                required_sip=0,
                required_return=None,
                probability_of_success=1.0 if (goal_amount is None or current_investment >= goal_amount) else 0.0,
                worst_case=current_investment,
                average_case=current_investment,
                best_case=current_investment,
                notes="Already at or past retirement age.",
            )

        monthly_r = (1 + expected_return) ** (1 / 12) - 1
        monthly_vol = return_volatility / np.sqrt(12)

        # Deterministic FV
        if monthly_r == 0:
            fv_sip = monthly_sip * months
        else:
            fv_sip = monthly_sip * (((1 + monthly_r) ** months - 1) / monthly_r)
        expected_corpus = current_investment * ((1 + monthly_r) ** months) + fv_sip

        # Inflation-adjusted goal default: current * (1+inf)^y * lifestyle multiple
        if goal_amount is None:
            # Heuristic: 25x annual expenses proxy from SIP * 12 * 20
            goal_amount = max(
                expected_corpus * 0.9,
                current_investment * ((1 + expected_inflation) ** years) * 3,
            )

        # Required SIP (deterministic)
        pv_goal_gap = goal_amount - current_investment * ((1 + monthly_r) ** months)
        if monthly_r == 0:
            required_sip = max(pv_goal_gap / months, 0)
        else:
            annuity_factor = ((1 + monthly_r) ** months - 1) / monthly_r
            required_sip = max(pv_goal_gap / annuity_factor, 0) if annuity_factor else 0

        # Required return (binary search on annual return for fixed SIP)
        required_return = self._required_return(
            current_investment, monthly_sip, months, goal_amount
        )

        # Monte Carlo
        rng = np.random.default_rng(seed)
        shocks = rng.normal(monthly_r, monthly_vol, size=(n_simulations, months))
        # Geometric path
        growth = np.cumprod(1 + shocks, axis=1)
        # Corpus = lumpsum growth + SIP contributions grown
        lumpsum = current_investment * growth[:, -1]
        # SIP: each month contribution grows for remaining months
        # Efficient: for each sim, sip_fv = sip * sum_{t=1..T} prod_{k=t..T} (1+r_k)
        # Approximate with: reverse cumprod
        rev = np.cumprod(1 + shocks[:, ::-1], axis=1)[:, ::-1]
        sip_fv = monthly_sip * rev.sum(axis=1)
        terminal = lumpsum + sip_fv

        p_success = float(np.mean(terminal >= goal_amount))
        worst = float(np.percentile(terminal, 5))
        avg = float(np.mean(terminal))
        best = float(np.percentile(terminal, 95))
        percentiles = {
            "p5": worst,
            "p25": float(np.percentile(terminal, 25)),
            "p50": float(np.percentile(terminal, 50)),
            "p75": float(np.percentile(terminal, 75)),
            "p95": best,
        }

        # Sample median path (simplified equal monthly step to median)
        median_path = []
        sample_paths = []
        # Build a few full paths for charting (subset)
        for i in range(min(20, n_simulations)):
            g = np.cumprod(1 + shocks[i])
            lm = current_investment * g
            rev_i = np.cumprod(1 + shocks[i, ::-1])[::-1]
            # Approximate running corpus
            running = []
            corpus = current_investment
            for m in range(months):
                corpus = corpus * (1 + shocks[i, m]) + monthly_sip
                running.append(float(corpus))
            sample_paths.append(running[:: max(1, months // 60)])  # downsample

        # Median path
        corpus = current_investment
        for m in range(months):
            corpus = corpus * (1 + monthly_r) + monthly_sip
            if m % max(1, months // 60) == 0 or m == months - 1:
                median_path.append(float(corpus))

        return GoalPlanResult(
            years=years,
            expected_corpus=round(expected_corpus, 2),
            required_sip=round(required_sip, 2),
            required_return=round(required_return, 4) if required_return is not None else None,
            probability_of_success=round(p_success, 4),
            worst_case=round(worst, 2),
            average_case=round(avg, 2),
            best_case=round(best, 2),
            percentiles={k: round(v, 2) for k, v in percentiles.items()},
            monthly_path_median=median_path,
            simulation_paths_sample=sample_paths,
            notes=(
                f"Monte Carlo with {n_simulations} paths, annual vol={return_volatility:.0%}, "
                f"goal=₹{goal_amount:,.0f}. Inflation assumption {expected_inflation:.1%} used for context only."
            ),
        )

    def _required_return(
        self,
        current: float,
        sip: float,
        months: int,
        goal: float,
    ) -> Optional[float]:
        lo, hi = -0.5, 0.5
        for _ in range(60):
            mid = (lo + hi) / 2
            mr = (1 + mid) ** (1 / 12) - 1
            if mr == 0:
                fv = current + sip * months
            else:
                fv = current * ((1 + mr) ** months) + sip * (((1 + mr) ** months - 1) / mr)
            if fv < goal:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
