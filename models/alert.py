"""Compatibility re-export — canonical definitions live in services.alerts.db_models."""

from __future__ import annotations

from services.alerts.db_models import Alert, AlertRule

__all__ = ["Alert", "AlertRule"]
