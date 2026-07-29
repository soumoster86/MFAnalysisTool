"""Mutual fund related ORM models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.session import Base


class Fund(Base):
    """Master mutual fund scheme record."""

    __tablename__ = "funds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amfi_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    scheme_name: Mapped[str] = mapped_column(String(512), index=True)
    amc: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    benchmark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    expense_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_load: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    min_sip: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_lumpsum: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fund_manager: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    fund_manager_tenure_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    launch_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    aum_cr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    riskometer: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    isin_growth: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    isin_div: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    cash_allocation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    debt_allocation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    equity_allocation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    international_exposure: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latest_nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    nav_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="amfi")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    holdings: Mapped[list["FundHolding"]] = relationship(back_populates="fund", cascade="all, delete-orphan")
    navs: Mapped[list["FundNAV"]] = relationship(back_populates="fund", cascade="all, delete-orphan")
    metrics: Mapped[list["FundMetric"]] = relationship(back_populates="fund", cascade="all, delete-orphan")


class FundNAV(Base):
    """Historical NAV time series."""

    __tablename__ = "fund_navs"
    __table_args__ = (UniqueConstraint("fund_id", "nav_date", name="uq_fund_nav_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"), index=True)
    nav_date: Mapped[date] = mapped_column(Date, index=True)
    nav: Mapped[float] = mapped_column(Float)
    repurchase_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sale_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    fund: Mapped["Fund"] = relationship(back_populates="navs")


class FundHolding(Base):
    """Portfolio holding snapshot for a fund."""

    __tablename__ = "fund_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"), index=True)
    as_of_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    security_name: Mapped[str] = mapped_column(String(512))
    isin: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    market_cap: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Large/Mid/Small
    weight_pct: Mapped[float] = mapped_column(Float, default=0.0)
    country: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default="India")
    asset_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default="Equity")

    fund: Mapped["Fund"] = relationship(back_populates="holdings")


class FundMetric(Base):
    """Cached risk/return metrics for a fund."""

    __tablename__ = "fund_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    period: Mapped[str] = mapped_column(String(32), default="3Y")  # 1Y, 3Y, 5Y
    cagr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volatility: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sortino: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    alpha: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    beta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    treynor: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    information_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    upside_capture: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    downside_capture: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    fund: Mapped["Fund"] = relationship(back_populates="metrics")
