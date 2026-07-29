"""Portfolio vault — persistent save/load of user portfolios (Slice A)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from database import session as db_session
from models.portfolio import Portfolio, PortfolioHolding
from utils.logging_config import get_logger

logger = get_logger(__name__)


class VaultError(Exception):
    pass


class PortfolioVaultService:
    """CRUD for named portfolios owned by a user."""

    def ensure_db(self) -> None:
        db_session.init_db()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """
        Best-effort column adds for older SQLite DBs.
        On Postgres/Supabase, create_all() in init_db is sufficient for new deploys.
        """
        from sqlalchemy import text

        url = str(db_session.engine.url)
        if not url.startswith("sqlite"):
            return  # Postgres: no SQLite-style ALTER loop needed

        alters = [
            ("portfolios", "source", "VARCHAR(64) DEFAULT 'manual'"),
            ("portfolios", "description", "TEXT"),
            ("portfolios", "as_of_date", "VARCHAR(32)"),
            ("portfolios", "total_invested", "FLOAT"),
            ("portfolios", "total_market_value", "FLOAT"),
            ("portfolios", "holdings_count", "INTEGER DEFAULT 0"),
            ("portfolios", "is_default", "BOOLEAN DEFAULT 0"),
            ("portfolio_holdings", "market_value", "FLOAT"),
            ("portfolio_holdings", "folio", "VARCHAR(128)"),
            ("portfolio_holdings", "holding_type", "VARCHAR(32)"),
        ]
        try:
            with db_session.engine.begin() as conn:
                for table, col, typedef in alters:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"))
                    except Exception:
                        pass  # column exists
        except Exception as exc:
            logger.debug("Schema ensure skipped: {}", exc)

    def list_portfolios(self, user_id: int) -> list[dict[str, Any]]:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            rows = (
                db.query(Portfolio)
                .filter(Portfolio.user_id == user_id)
                .order_by(Portfolio.updated_at.desc())
                .all()
            )
            return [self._portfolio_summary(p) for p in rows]

    def get_portfolio(
        self, portfolio_id: int, user_id: int, *, include_holdings: bool = True
    ) -> dict[str, Any]:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            p = (
                db.query(Portfolio)
                .filter(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
                .one_or_none()
            )
            if not p:
                raise VaultError("Portfolio not found")
            return self._portfolio_detail(p, include_holdings=include_holdings)

    def create_portfolio(
        self,
        user_id: int,
        name: str,
        holdings: list[dict[str, Any]],
        *,
        source: str = "manual",
        description: Optional[str] = None,
        as_of_date: Optional[str] = None,
        set_default: bool = False,
    ) -> dict[str, Any]:
        self.ensure_db()
        name = (name or "My Portfolio").strip()[:256]
        with db_session.SessionLocal() as db:
            if set_default:
                self._clear_default(db, user_id)
            p = Portfolio(
                user_id=user_id,
                name=name,
                source=source,
                description=description,
                as_of_date=as_of_date,
                is_default=set_default,
            )
            db.add(p)
            db.flush()
            self._replace_holdings(db, p, holdings)
            db.commit()
            db.refresh(p)
            logger.info("Created portfolio {} for user {}", p.id, user_id)
            return self._portfolio_detail(p)

    def update_portfolio(
        self,
        portfolio_id: int,
        user_id: int,
        *,
        name: Optional[str] = None,
        holdings: Optional[list[dict[str, Any]]] = None,
        description: Optional[str] = None,
        as_of_date: Optional[str] = None,
        source: Optional[str] = None,
        set_default: Optional[bool] = None,
    ) -> dict[str, Any]:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            p = (
                db.query(Portfolio)
                .filter(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
                .one_or_none()
            )
            if not p:
                raise VaultError("Portfolio not found")
            if name is not None:
                p.name = name.strip()[:256]
            if description is not None:
                p.description = description
            if as_of_date is not None:
                p.as_of_date = as_of_date
            if source is not None:
                p.source = source
            if set_default is True:
                self._clear_default(db, user_id)
                p.is_default = True
            elif set_default is False:
                p.is_default = False
            if holdings is not None:
                self._replace_holdings(db, p, holdings)
            p.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(p)
            return self._portfolio_detail(p)

    def delete_portfolio(self, portfolio_id: int, user_id: int) -> bool:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            p = (
                db.query(Portfolio)
                .filter(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
                .one_or_none()
            )
            if not p:
                return False
            db.delete(p)
            db.commit()
            logger.info("Deleted portfolio {} for user {}", portfolio_id, user_id)
            return True

    def save_session_holdings(
        self,
        user_id: int,
        holdings: list[dict[str, Any]],
        *,
        name: Optional[str] = None,
        portfolio_id: Optional[int] = None,
        source: str = "manual",
        as_of_date: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Save current working holdings into vault.
        If portfolio_id given → update; else create new.
        """
        if portfolio_id:
            return self.update_portfolio(
                portfolio_id,
                user_id,
                name=name,
                holdings=holdings,
                source=source,
                as_of_date=as_of_date,
                description=description,
            )
        return self.create_portfolio(
            user_id,
            name or f"Portfolio {datetime.utcnow():%Y-%m-%d %H:%M}",
            holdings,
            source=source,
            as_of_date=as_of_date,
            description=description,
            set_default=True,
        )

    def get_default_portfolio(self, user_id: int) -> Optional[dict[str, Any]]:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            p = (
                db.query(Portfolio)
                .filter(Portfolio.user_id == user_id, Portfolio.is_default.is_(True))
                .one_or_none()
            )
            if not p:
                p = (
                    db.query(Portfolio)
                    .filter(Portfolio.user_id == user_id)
                    .order_by(Portfolio.updated_at.desc())
                    .first()
                )
            if not p:
                return None
            return self._portfolio_detail(p)

    def holdings_for_analyzer(self, portfolio: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert vault holdings to session/analyzer shape."""
        out = []
        for h in portfolio.get("holdings") or []:
            out.append(
                {
                    "amfi_code": str(h.get("amfi_code") or ""),
                    "scheme_name": h.get("scheme_name") or "",
                    "invested_amount": float(h.get("invested_amount") or 0),
                    "units": float(h.get("units") or 0),
                    "sip_amount": float(h.get("sip_amount") or 0),
                    "market_value": h.get("market_value"),
                    "current_nav": h.get("current_nav"),
                    "nav": h.get("current_nav"),
                    "folio": h.get("folio"),
                    "holding_type": h.get("holding_type"),
                }
            )
        return out

    # ---------------------------------------------------------------- internal
    def _replace_holdings(
        self, db: Session, portfolio: Portfolio, holdings: list[dict[str, Any]]
    ) -> None:
        db.query(PortfolioHolding).filter(
            PortfolioHolding.portfolio_id == portfolio.id
        ).delete()
        total_inv = 0.0
        total_mkt = 0.0
        count = 0
        for h in holdings:
            code = str(h.get("amfi_code") or "").strip()
            name = str(h.get("scheme_name") or code or "Unknown")
            invested = float(h.get("invested_amount") or 0)
            units = float(h.get("units") or 0)
            mkt = h.get("market_value")
            try:
                mkt_f = float(mkt) if mkt is not None else None
            except (TypeError, ValueError):
                mkt_f = None
            nav = h.get("current_nav") or h.get("nav") or h.get("avg_nav")
            try:
                nav_f = float(nav) if nav is not None else None
            except (TypeError, ValueError):
                nav_f = None
            if mkt_f is None and units and nav_f:
                mkt_f = units * nav_f
            if invested <= 0 and mkt_f:
                invested = mkt_f
            total_inv += invested
            total_mkt += mkt_f or invested
            count += 1
            db.add(
                PortfolioHolding(
                    portfolio_id=portfolio.id,
                    amfi_code=code or None,
                    scheme_name=name[:512],
                    units=units,
                    invested_amount=invested,
                    market_value=mkt_f,
                    current_nav=nav_f,
                    avg_nav=nav_f,
                    sip_amount=float(h.get("sip_amount") or 0) or None,
                    folio=(str(h.get("folio"))[:128] if h.get("folio") else None),
                    holding_type=(
                        str(h.get("holding_type"))[:32] if h.get("holding_type") else None
                    ),
                )
            )
        portfolio.total_invested = round(total_inv, 2)
        portfolio.total_market_value = round(total_mkt, 2)
        portfolio.holdings_count = count
        portfolio.updated_at = datetime.utcnow()

    def _clear_default(self, db: Session, user_id: int) -> None:
        db.query(Portfolio).filter(
            Portfolio.user_id == user_id, Portfolio.is_default.is_(True)
        ).update({"is_default": False})

    def _portfolio_summary(self, p: Portfolio) -> dict[str, Any]:
        return {
            "id": p.id,
            "name": p.name,
            "source": p.source,
            "as_of_date": p.as_of_date,
            "description": p.description,
            "total_invested": p.total_invested,
            "total_market_value": p.total_market_value,
            "holdings_count": p.holdings_count or len(p.holdings or []),
            "is_default": bool(p.is_default),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }

    def _portfolio_detail(
        self, p: Portfolio, *, include_holdings: bool = True
    ) -> dict[str, Any]:
        d = self._portfolio_summary(p)
        if include_holdings:
            d["holdings"] = [
                {
                    "id": h.id,
                    "amfi_code": h.amfi_code,
                    "scheme_name": h.scheme_name,
                    "units": h.units,
                    "invested_amount": h.invested_amount,
                    "market_value": h.market_value,
                    "current_nav": h.current_nav,
                    "avg_nav": h.avg_nav,
                    "sip_amount": h.sip_amount,
                    "folio": h.folio,
                    "holding_type": h.holding_type,
                }
                for h in (p.holdings or [])
            ]
        return d
