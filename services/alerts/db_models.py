"""
Alert ORM tables — single source of truth for Slice B.

Only depends on database.session.Base. Never import models.* from here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from database.session import Base

# Bump when changing schema so Cloud deploys are easy to verify in logs
ALERT_ORM_VERSION = "2026-07-29-b5"


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    portfolio_id = Column(Integer, nullable=True, index=True)
    rule_id = Column(Integer, nullable=True, index=True)
    alert_type = Column(String(64), index=True, nullable=False, default="info")
    severity = Column(String(16), default="info")
    title = Column(String(256), nullable=False, default="")
    message = Column(Text, nullable=False, default="")
    amfi_code = Column(String(20), nullable=True, index=True)
    scheme_name = Column(String(512), nullable=True)
    metric_value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    fingerprint = Column(String(256), nullable=True, index=True)
    payload = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    name = Column(String(128), nullable=False, default="rule")
    alert_type = Column(String(64), index=True, nullable=False, default="nav_drop")
    enabled = Column(Boolean, default=True)
    threshold = Column(Float, default=-0.03)
    lookback_days = Column(Integer, default=1)
    severity = Column(String(16), default="warning")
    scope = Column(String(32), default="fund")
    amfi_code = Column(String(20), nullable=True)
    portfolio_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
