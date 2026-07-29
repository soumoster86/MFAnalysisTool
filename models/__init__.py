"""ORM models package — lazy exports to avoid circular / partial imports."""

from __future__ import annotations

from models.fund import Fund, FundHolding, FundNAV, FundMetric
from models.portfolio import Portfolio, PortfolioHolding
from models.user import User

# Alert models are defined in services.alerts.db_models (imported lazily below)
# so `import models` during init_db never depends on the alerts package graph.

__all__ = [
    "Fund",
    "FundHolding",
    "FundNAV",
    "FundMetric",
    "Portfolio",
    "PortfolioHolding",
    "Alert",
    "AlertRule",
    "User",
]


def __getattr__(name: str):
    if name in ("Alert", "AlertRule"):
        from services.alerts.db_models import Alert, AlertRule

        return Alert if name == "Alert" else AlertRule
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
