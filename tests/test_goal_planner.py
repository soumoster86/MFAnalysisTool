"""Tests for goal planner Monte Carlo."""

from analytics.goal_planner import GoalPlanner


def test_goal_plan_basic() -> None:
    res = GoalPlanner().plan(
        age=30,
        retirement_age=45,
        current_investment=100_000,
        monthly_sip=10_000,
        expected_return=0.12,
        goal_amount=5_000_000,
        n_simulations=300,
        seed=1,
    )
    assert res.years == 15
    assert res.expected_corpus > 0
    assert 0 <= res.probability_of_success <= 1
    assert res.worst_case <= res.average_case <= res.best_case


def test_already_retired() -> None:
    res = GoalPlanner().plan(
        age=65,
        retirement_age=60,
        current_investment=1_000_000,
        monthly_sip=0,
        expected_return=0.08,
        goal_amount=500_000,
        n_simulations=100,
    )
    assert res.years == 0
