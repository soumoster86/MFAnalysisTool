"""Alert / notification and user rule models (Slice B)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.session import Base


class Alert(Base):
    """Fired alert instance for a fund/portfolio event."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    portfolio_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")  # info/warning/critical
    title: Mapped[str] = mapped_column(String(256))
    message: Mapped[str] = mapped_column(Text)
    amfi_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    scheme_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    metric_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Dedupe key: type + scope + calendar day (or similar)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON extras
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AlertRule(Base):
    """User or system rule that the evaluation engine checks."""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Threshold semantics depend on alert_type (see services/alerts/rules.py)
    threshold: Mapped[float] = mapped_column(Float, default=-0.03)
    lookback_days: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    # fund = per holding; portfolio = whole book
    scope: Mapped[str] = mapped_column(String(32), default="fund")
    amfi_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    portfolio_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
