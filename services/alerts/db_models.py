"""
Alert ORM tables — single source of truth for Slice B.

Only depends on database.session.Base. Never import models.* from here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from database.session import Base

# Bump when changing schema so Cloud deploys are easy to verify in logs
ALERT_ORM_VERSION = "2026-07-29-c1"


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


class FundSnapshot(Base):
    """Point-in-time copy of a fund's mutable attributes.

    Change alerts (manager, TER, category, benchmark, holdings, sector mix,
    risk) can only fire by comparing two points in time. Nothing else in the
    schema keeps history for these fields — `funds` is overwritten in place —
    so the change detector records its own.
    """

    __tablename__ = "fund_snapshots"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    amfi_code = Column(String(20), index=True, nullable=False)
    scheme_name = Column(String(512), nullable=True)
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)

    fund_manager = Column(String(256), nullable=True)
    expense_ratio = Column(Float, nullable=True)
    category = Column(String(128), nullable=True)
    subcategory = Column(String(128), nullable=True)
    benchmark = Column(String(256), nullable=True)
    riskometer = Column(String(64), nullable=True)
    aum_cr = Column(Float, nullable=True)

    # Annualised volatility, for risk_increase.
    volatility = Column(Float, nullable=True)

    holdings_count = Column(Integer, nullable=True)
    # Hash of (security, rounded weight) pairs — cheap "did anything move?" test.
    holdings_hash = Column(String(64), nullable=True)
    # JSON: {security_name: weight_pct}
    holdings_json = Column(Text, nullable=True)
    # JSON: {sector: weight_pct}
    sector_json = Column(Text, nullable=True)

    # Where the snapshot's inputs came from — a snapshot built on sample
    # holdings must never fire a "holdings changed" alert.
    holdings_source = Column(String(32), nullable=True)
    nav_source = Column(String(32), nullable=True)


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
