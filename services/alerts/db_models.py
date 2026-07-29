"""
Alert ORM tables (Slice B).

Kept under services/alerts (not models.*) so Streamlit multipage imports
never hit a partially-initialized `models` package — a common Cloud failure mode.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.session import Base


class Alert(Base):
    """Fired alert instance for a fund/portfolio event."""

    __tablename__ = "alerts"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    portfolio_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    rule_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(256))
    message: Mapped[str] = mapped_column(Text)
    amfi_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    scheme_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    metric_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AlertRule(Base):
    """User or system rule that the evaluation engine checks."""

    __tablename__ = "alert_rules"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold: Mapped[float] = mapped_column(Float, default=-0.03)
    lookback_days: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    scope: Mapped[str] = mapped_column(String(32), default="fund")
    amfi_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    portfolio_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
