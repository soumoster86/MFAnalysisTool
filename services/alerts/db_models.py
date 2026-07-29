"""Alert ORM tables (Slice B) — classic Column API for max SQLAlchemy compatibility."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from database.session import Base


class Alert(Base):
    """Fired alert instance for a fund/portfolio event."""

    __tablename__ = "alerts"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    portfolio_id = Column(Integer, nullable=True, index=True)
    rule_id = Column(Integer, nullable=True, index=True)
    alert_type = Column(String(64), index=True, nullable=False)
    severity = Column(String(16), default="info")
    title = Column(String(256), nullable=False)
    message = Column(Text, nullable=False)
    amfi_code = Column(String(20), nullable=True, index=True)
    scheme_name = Column(String(512), nullable=True)
    metric_value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    fingerprint = Column(String(256), nullable=True, index=True)
    payload = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AlertRule(Base):
    """User or system rule that the evaluation engine checks."""

    __tablename__ = "alert_rules"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    name = Column(String(128), nullable=False)
    alert_type = Column(String(64), index=True, nullable=False)
    enabled = Column(Boolean, default=True)
    threshold = Column(Float, default=-0.03)
    lookback_days = Column(Integer, default=1)
    severity = Column(String(16), default="warning")
    scope = Column(String(32), default="fund")
    amfi_code = Column(String(20), nullable=True)
    portfolio_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
