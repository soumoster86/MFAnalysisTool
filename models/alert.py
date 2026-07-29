"""
Re-export alert ORM from services.alerts.db_models.

AlertService must import from services.alerts.db_models directly (not this
module) to avoid Streamlit Cloud circular ImportError on AlertRule.
"""

from __future__ import annotations

from services.alerts.db_models import Alert, AlertRule

__all__ = ["Alert", "AlertRule"]
