"""Alert / notification models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.session import Base


class Alert(Base):
    """System or user alert for fund/portfolio events."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")  # info/warning/critical
    title: Mapped[str] = mapped_column(String(256))
    message: Mapped[str] = mapped_column(Text)
    amfi_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    scheme_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
