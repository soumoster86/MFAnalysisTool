"""Default alert rule catalogue and type metadata (Slice B)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

AlertType = Literal[
    # NAV / portfolio maths — evaluated from a time series that already exists.
    "nav_drop",
    "period_return",
    "drawdown",
    "pnl",
    "concentration",
    "overlap",
    # Change detection — needs two FundSnapshot rows to compare.
    # See services.alerts.change_detector.
    "manager_change",
    "expense_ratio_change",
    "category_change",
    "benchmark_change",
    "holdings_change",
    "large_holding_change",
    "sector_shift",
    "risk_increase",
]

# Types that require snapshot history rather than NAV maths.
CHANGE_ALERT_TYPES: list[str] = [
    "manager_change",
    "expense_ratio_change",
    "category_change",
    "benchmark_change",
    "holdings_change",
    "large_holding_change",
    "sector_shift",
    "risk_increase",
]

RULE_HELP: dict[str, str] = {
    "nav_drop": "Fires when 1-day NAV return is at or below threshold (e.g. -3%).",
    "period_return": "Fires when N-day NAV return is at or below threshold.",
    "drawdown": "Fires when peak-to-trough drawdown is at or below threshold (more negative = worse).",
    "pnl": "Fires when unrealized P&L on a holding is at or below threshold (e.g. -10%).",
    "concentration": "Fires when a single fund weight is at or above threshold (e.g. 40%).",
    "overlap": "Fires when pairwise stock-level fund overlap is at or above threshold.",
    "manager_change": "Fires when the fund manager on record changes. Threshold not used.",
    "expense_ratio_change": "Fires when TER moves by at least threshold percentage points (e.g. 0.10 = 0.10pp).",
    "category_change": "Fires when the fund's category or sub-category is reclassified. Threshold not used.",
    "benchmark_change": "Fires when the stated benchmark index changes. Threshold not used.",
    "holdings_change": "Fires when at least threshold of the portfolio turns over by weight (e.g. 0.20 = 20%).",
    "large_holding_change": "Fires when any single security's weight moves by threshold percentage points (e.g. 2.0 = 2pp).",
    "sector_shift": "Fires when any sector's weight moves by threshold percentage points (e.g. 5.0 = 5pp).",
    "risk_increase": "Fires when annualised volatility rises by at least threshold, or the riskometer steps up (e.g. 0.25 = +25%).",
}


def is_change_type(alert_type: str) -> bool:
    """True when the type needs snapshot history rather than NAV maths."""
    return alert_type in CHANGE_ALERT_TYPES


@dataclass
class RuleSpec:
    """In-memory rule template (system default or user override)."""

    name: str
    alert_type: str
    threshold: float
    lookback_days: int = 1
    severity: str = "warning"
    scope: str = "fund"  # fund | portfolio
    enabled: bool = True
    amfi_code: str | None = None
    portfolio_id: int | None = None
    id: int | None = None
    user_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["help"] = RULE_HELP.get(self.alert_type, "")
        return d


# Built-in defaults used when the user has no custom rules
DEFAULT_RULE_SPECS: list[RuleSpec] = [
    RuleSpec(
        name="Daily NAV drop ≥ 3%",
        alert_type="nav_drop",
        threshold=-0.03,
        lookback_days=1,
        severity="warning",
        scope="fund",
    ),
    RuleSpec(
        name="5-day return ≤ -5%",
        alert_type="period_return",
        threshold=-0.05,
        lookback_days=5,
        severity="warning",
        scope="fund",
    ),
    RuleSpec(
        name="20-day return ≤ -10%",
        alert_type="period_return",
        threshold=-0.10,
        lookback_days=20,
        severity="critical",
        scope="fund",
    ),
    RuleSpec(
        name="Drawdown ≥ 15%",
        alert_type="drawdown",
        threshold=-0.15,
        lookback_days=365,
        severity="critical",
        scope="fund",
    ),
    RuleSpec(
        name="Unrealized loss ≥ 10%",
        alert_type="pnl",
        threshold=-0.10,
        lookback_days=0,
        severity="warning",
        scope="fund",
    ),
    RuleSpec(
        name="Single fund > 40% of book",
        alert_type="concentration",
        threshold=0.40,
        lookback_days=0,
        severity="info",
        scope="portfolio",
    ),
    RuleSpec(
        name="Fund pair overlap > 40%",
        alert_type="overlap",
        threshold=0.40,
        lookback_days=0,
        severity="info",
        scope="portfolio",
    ),
    # --- change detection (needs snapshot history) ---
    RuleSpec(
        name="Fund manager changed",
        alert_type="manager_change",
        threshold=0.0,
        lookback_days=0,
        severity="critical",
        scope="fund",
    ),
    RuleSpec(
        name="Expense ratio moved ≥ 0.10pp",
        alert_type="expense_ratio_change",
        threshold=0.10,
        lookback_days=0,
        severity="warning",
        scope="fund",
    ),
    RuleSpec(
        name="Category reclassified",
        alert_type="category_change",
        threshold=0.0,
        lookback_days=0,
        severity="warning",
        scope="fund",
    ),
    RuleSpec(
        name="Benchmark changed",
        alert_type="benchmark_change",
        threshold=0.0,
        lookback_days=0,
        severity="warning",
        scope="fund",
    ),
    RuleSpec(
        name="Portfolio turnover ≥ 20%",
        alert_type="holdings_change",
        threshold=0.20,
        lookback_days=0,
        severity="warning",
        scope="fund",
    ),
    RuleSpec(
        name="Single holding moved ≥ 2pp",
        alert_type="large_holding_change",
        threshold=2.0,
        lookback_days=0,
        severity="info",
        scope="fund",
    ),
    RuleSpec(
        name="Sector allocation moved ≥ 5pp",
        alert_type="sector_shift",
        threshold=5.0,
        lookback_days=0,
        severity="info",
        scope="fund",
    ),
    RuleSpec(
        name="Volatility up ≥ 25%",
        alert_type="risk_increase",
        threshold=0.25,
        lookback_days=0,
        severity="warning",
        scope="fund",
    ),
]


def default_rules() -> list[RuleSpec]:
    """Fresh copies of system defaults."""
    return [
        RuleSpec(
            name=r.name,
            alert_type=r.alert_type,
            threshold=r.threshold,
            lookback_days=r.lookback_days,
            severity=r.severity,
            scope=r.scope,
            enabled=r.enabled,
        )
        for r in DEFAULT_RULE_SPECS
    ]


def known_alert_types() -> list[str]:
    return list(RULE_HELP.keys())
