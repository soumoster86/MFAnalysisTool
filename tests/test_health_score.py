"""Tests for fund health scorer."""

from analytics.health_score import FundHealthScorer


def test_score_bounds() -> None:
    scorer = FundHealthScorer()
    h = scorer.score(
        cagr=0.15,
        sharpe=1.2,
        sortino=1.5,
        max_drawdown=-0.18,
        volatility=0.14,
        alpha=0.02,
        beta=0.95,
        expense_ratio=0.6,
        aum_cr=5000,
        manager_tenure_years=6,
        top10_concentration=40,
        n_holdings=45,
    )
    assert 0 <= h.overall <= 100
    assert h.growth > 50
    assert h.narrative


def test_score_with_missing_data() -> None:
    h = FundHealthScorer().score()
    assert h.overall == 50.0
