"""User portfolio ORM models (vault)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.session import Base


class Portfolio(Base):
    """Named portfolio of mutual fund holdings belonging to a user."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), default="My Portfolio")
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # session | cas_import | manual | demo
    source: Mapped[str] = mapped_column(String(64), default="manual")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    as_of_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # denormalized totals for list views
    total_invested: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_market_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    holdings_count: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    holdings: Mapped[list["PortfolioHolding"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class PortfolioHolding(Base):
    """Single fund line item in a portfolio."""

    __tablename__ = "portfolio_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    fund_id: Mapped[Optional[int]] = mapped_column(ForeignKey("funds.id"), nullable=True)
    amfi_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    scheme_name: Mapped[str] = mapped_column(String(512))
    units: Mapped[float] = mapped_column(Float, default=0.0)
    invested_amount: Mapped[float] = mapped_column(Float, default=0.0)
    market_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sip_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    folio: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    holding_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # soa|demat|manual

    portfolio: Mapped["Portfolio"] = relationship(back_populates="holdings")
