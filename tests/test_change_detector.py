"""Fund attribute change detection (Module 13 change triggers)."""

from __future__ import annotations

import pandas as pd
import pytest

from services.alerts.change_detector import (
    Snapshot,
    build_snapshot,
    detect_changes,
)
from services.alerts.rules import CHANGE_ALERT_TYPES, RULE_HELP, is_change_type


def _snap(code: str = "100", **kw) -> Snapshot:
    base = dict(
        scheme_name="Test Fund",
        fund_manager="A. Manager",
        expense_ratio=1.00,
        category="Equity",
        subcategory="Flexi Cap",
        benchmark="NIFTY 500 TRI",
        riskometer="High",
        volatility=0.18,
        holdings={"HDFC Bank": 8.0, "Infosys": 6.0, "ITC": 4.0},
        sectors={"Financials": 20.0, "IT": 15.0},
        holdings_source="groww",
        nav_source="mfapi",
    )
    base.update(kw)
    return Snapshot(amfi_code=code, **base)


def _types(changes) -> set[str]:
    return {c.alert_type for c in changes}


# --------------------------------------------------------------- baseline
def test_first_snapshot_never_fires():
    # Otherwise every fund alerts once the moment it is first seen.
    assert detect_changes(None, _snap()) == []


def test_identical_snapshots_produce_nothing():
    assert detect_changes(_snap(), _snap()) == []


def test_comparing_different_funds_is_rejected():
    with pytest.raises(ValueError, match="different funds"):
        detect_changes(_snap("100"), _snap("200"))


# ------------------------------------------------------ categorical changes
def test_manager_change_fires_critical():
    changes = detect_changes(_snap(), _snap(fund_manager="B. Newperson"))
    assert _types(changes) == {"manager_change"}
    assert changes[0].severity == "critical"
    assert "A. Manager" in changes[0].message
    assert "B. Newperson" in changes[0].message


def test_benchmark_and_category_changes_fire():
    changes = detect_changes(
        _snap(), _snap(benchmark="NIFTY 100 TRI", subcategory="Large Cap")
    )
    assert _types(changes) == {"benchmark_change", "category_change"}


def test_missing_attribute_on_either_side_does_not_fire():
    # None -> value is a metadata backfill, not a real-world change.
    assert detect_changes(_snap(fund_manager=None), _snap()) == []
    assert detect_changes(_snap(), _snap(fund_manager=None)) == []


def test_riskometer_step_up_fires_but_step_down_does_not():
    up = detect_changes(_snap(riskometer="Moderate"), _snap(riskometer="Very High"))
    assert "risk_increase" in _types(up)

    down = detect_changes(_snap(riskometer="Very High"), _snap(riskometer="Moderate"))
    assert "risk_increase" not in _types(down)


def test_riskometer_tolerates_wording_variants():
    changes = detect_changes(
        _snap(riskometer="Moderate"), _snap(riskometer="Very High Risk")
    )
    assert "risk_increase" in _types(changes)


# ---------------------------------------------------------- expense ratio
def test_expense_ratio_rise_beyond_threshold_fires_as_warning():
    changes = detect_changes(_snap(), _snap(expense_ratio=1.20))
    assert _types(changes) == {"expense_ratio_change"}
    assert changes[0].severity == "warning"
    assert changes[0].metric_value == pytest.approx(0.20)


def test_expense_ratio_fall_is_informational_not_a_warning():
    # A cheaper fund is not bad news for the investor.
    changes = detect_changes(_snap(), _snap(expense_ratio=0.80))
    assert changes[0].severity == "info"


def test_expense_ratio_move_below_threshold_is_ignored():
    assert detect_changes(_snap(), _snap(expense_ratio=1.02)) == []


# -------------------------------------------------------------- holdings
def test_portfolio_turnover_fires_and_lists_added_and_removed():
    previous = _snap(holdings={"HDFC Bank": 50.0, "Infosys": 50.0})
    current = _snap(holdings={"HDFC Bank": 50.0, "Reliance": 50.0})
    changes = detect_changes(previous, current)
    holdings_change = next(c for c in changes if c.alert_type == "holdings_change")
    assert holdings_change.metric_value == pytest.approx(0.50)
    assert holdings_change.payload["added"] == ["Reliance"]
    assert holdings_change.payload["removed"] == ["Infosys"]


def test_turnover_is_a_fraction_of_actual_weight_not_of_100():
    # Providers often return only the top N holdings, so the weights need not
    # sum to 100. Swapping half of a 14-point book is 50% turnover, not 7%.
    previous = _snap(holdings={"HDFC Bank": 8.0, "Infosys": 6.0})
    current = _snap(holdings={"Reliance": 8.0, "Infosys": 6.0})
    changes = detect_changes(previous, current)
    holdings_change = next(c for c in changes if c.alert_type == "holdings_change")
    assert holdings_change.metric_value == pytest.approx(8.0 / 14.0, rel=1e-3)


def test_empty_holdings_on_one_side_does_not_divide_by_zero():
    assert detect_changes(_snap(holdings={}), _snap()) == []
    assert detect_changes(_snap(), _snap(holdings={})) == []


def test_large_single_holding_move_reports_the_biggest_mover():
    previous = _snap(holdings={"HDFC Bank": 8.0, "Infosys": 6.0})
    current = _snap(holdings={"HDFC Bank": 13.0, "Infosys": 6.5})
    changes = detect_changes(previous, current)
    move = next(c for c in changes if c.alert_type == "large_holding_change")
    assert move.payload["security"] == "HDFC Bank"
    assert move.metric_value == pytest.approx(5.0)


def test_small_holding_drift_does_not_fire():
    previous = _snap(holdings={"HDFC Bank": 8.0, "Infosys": 6.0})
    current = _snap(holdings={"HDFC Bank": 8.4, "Infosys": 5.8})
    assert "large_holding_change" not in _types(detect_changes(previous, current))


def test_sector_shift_fires_on_the_largest_move():
    previous = _snap(sectors={"Financials": 20.0, "IT": 15.0})
    current = _snap(sectors={"Financials": 30.0, "IT": 14.0})
    changes = detect_changes(previous, current)
    shift = next(c for c in changes if c.alert_type == "sector_shift")
    assert shift.payload["sector"] == "Financials"
    assert shift.metric_value == pytest.approx(10.0)


# ------------------------------------------------- fabricated-data guard
def test_sample_holdings_never_produce_holdings_alerts():
    # Sample holdings are synthesised per fund; comparing them yields
    # confident nonsense. This is the guard that prevents it.
    previous = _snap(holdings={"A": 50.0}, holdings_source="sample")
    current = _snap(holdings={"B": 50.0}, holdings_source="sample")
    changes = detect_changes(previous, current)
    assert not ({"holdings_change", "large_holding_change", "sector_shift"} & _types(changes))


def test_one_fabricated_side_is_enough_to_suppress_holdings_alerts():
    previous = _snap(holdings={"A": 50.0}, holdings_source="groww")
    current = _snap(holdings={"B": 50.0}, holdings_source="sample")
    assert "holdings_change" not in _types(detect_changes(previous, current))


def test_synthetic_nav_never_produces_a_risk_increase():
    previous = _snap(volatility=0.10, nav_source="synthetic")
    current = _snap(volatility=0.30, nav_source="synthetic")
    assert "risk_increase" not in _types(detect_changes(previous, current))


def test_fabricated_holdings_do_not_suppress_manager_change():
    # Attribute changes come from meta, not holdings — they stay valid.
    previous = _snap(holdings_source="sample")
    current = _snap(fund_manager="B. Newperson", holdings_source="sample")
    assert "manager_change" in _types(detect_changes(previous, current))


# --------------------------------------------------------- risk increase
def test_volatility_jump_fires():
    changes = detect_changes(_snap(volatility=0.16), _snap(volatility=0.24))
    risk = next(c for c in changes if c.alert_type == "risk_increase")
    assert risk.metric_value == pytest.approx(0.50)


def test_volatility_fall_does_not_fire():
    assert "risk_increase" not in _types(
        detect_changes(_snap(volatility=0.24), _snap(volatility=0.16))
    )


def test_zero_previous_volatility_does_not_divide_by_zero():
    assert detect_changes(_snap(volatility=0.0), _snap(volatility=0.2)) == []


# ------------------------------------------------------------- rule wiring
class _Rule:
    def __init__(self, alert_type, threshold=0.0, enabled=True):
        self.alert_type = alert_type
        self.threshold = threshold
        self.enabled = enabled


def test_rules_restrict_which_change_types_can_fire():
    previous = _snap()
    current = _snap(fund_manager="B. Newperson", expense_ratio=1.50)
    only_manager = detect_changes(previous, current, rules=[_Rule("manager_change")])
    assert _types(only_manager) == {"manager_change"}


def test_disabled_rule_does_not_fire():
    changes = detect_changes(
        _snap(),
        _snap(fund_manager="B. Newperson"),
        rules=[_Rule("manager_change", enabled=False), _Rule("nav_drop")],
    )
    assert changes == []


def test_rule_threshold_overrides_the_default():
    previous, current = _snap(), _snap(expense_ratio=1.05)
    # Default threshold is 0.10pp, so a 0.05 move is below it.
    assert detect_changes(
        previous, current, rules=[_Rule("expense_ratio_change", threshold=0.10)]
    ) == []
    tighter = detect_changes(
        previous, current, rules=[_Rule("expense_ratio_change", threshold=0.01)]
    )
    assert _types(tighter) == {"expense_ratio_change"}


def test_zero_threshold_keeps_the_default_instead_of_firing_on_noise():
    # Categorical rules carry threshold=0 because the field is meaningless to
    # them; honouring that zero on a magnitude type would alert on provider
    # rounding noise every scan.
    previous, current = _snap(expense_ratio=1.0000), _snap(expense_ratio=1.0001)
    assert detect_changes(
        previous, current, rules=[_Rule("expense_ratio_change", threshold=0.0)]
    ) == []


# ------------------------------------------------------------- snapshotting
class _FakeFundService:
    def __init__(self, meta, holdings=None):
        self._meta = meta
        self._holdings = holdings

    def get_fund_meta(self, code, enrich=False):
        return self._meta

    def get_holdings(self, code, name=None):
        if self._holdings is None:
            raise RuntimeError("no holdings")
        return self._holdings

    def get_holdings_source(self, code):
        return "groww"

    def get_nav_source(self, code):
        return "mfapi"

    def get_nav_history(self, code, scheme_name=None, years=1.0):
        raise RuntimeError("offline")


def test_build_snapshot_reads_meta_and_holdings():
    holdings = pd.DataFrame(
        [
            {"security_name": "HDFC Bank", "weight_pct": 8.0, "sector": "Financials"},
            {"security_name": "Infosys", "weight_pct": 6.0, "sector": "IT"},
        ]
    )
    svc = _FakeFundService(
        {
            "scheme_name": "Test Fund",
            "fund_manager": "A. Manager",
            "expense_ratio": "1.25",
            "category": "Equity",
            "benchmark": "NIFTY 500 TRI",
        },
        holdings,
    )
    snap = build_snapshot(svc, "100")
    assert snap.fund_manager == "A. Manager"
    assert snap.expense_ratio == 1.25  # coerced from string
    assert snap.holdings == {"HDFC Bank": 8.0, "Infosys": 6.0}
    assert snap.sectors == {"Financials": 8.0, "IT": 6.0}
    assert snap.holdings_count == 2
    assert snap.holdings_hash


def test_build_snapshot_survives_a_failing_provider():
    # A partial snapshot is still useful; a missing field simply cannot
    # produce a change alert.
    svc = _FakeFundService({"scheme_name": "Test Fund"}, holdings=None)
    snap = build_snapshot(svc, "100")
    assert snap.scheme_name == "Test Fund"
    assert snap.holdings == {}
    assert snap.volatility is None


def test_fractional_weights_are_normalised_to_percent_points():
    holdings = pd.DataFrame(
        [{"security_name": "HDFC Bank", "weight_pct": 0.08, "sector": "Financials"}]
    )
    svc = _FakeFundService({"scheme_name": "T"}, holdings)
    snap = build_snapshot(svc, "100")
    assert snap.holdings["HDFC Bank"] == pytest.approx(8.0)


# ----------------------------------------------------------------- catalogue
def test_every_change_type_is_documented_and_recognised():
    for atype in CHANGE_ALERT_TYPES:
        assert atype in RULE_HELP, f"{atype} missing from RULE_HELP"
        assert is_change_type(atype)


def test_nav_types_are_not_treated_as_change_types():
    for atype in ("nav_drop", "drawdown", "pnl", "concentration", "overlap"):
        assert not is_change_type(atype)
