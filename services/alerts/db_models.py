"""Compatibility re-export — canonical ORM lives in models.alert."""

from __future__ import annotations

from models.alert import Alert, AlertRule

__all__ = ["Alert", "AlertRule"]
