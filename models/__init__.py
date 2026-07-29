"""ORM models package."""

from __future__ import annotations

from models.fund import Fund, FundHolding, FundNAV, FundMetric
from models.portfolio import Portfolio, PortfolioHolding
from models.user import User

# Prefer services path so only one SQLAlchemy registry entry exists for alerts
from services.alerts.db_models import Alert, AlertRule

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
