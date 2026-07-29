"""High-level fund data service: AMFI + real NAV history + live holdings."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from analytics.health_score import FundHealthScorer
from analytics.risk_metrics import RiskMetricsCalculator
from config.settings import settings
from database.session import SessionLocal, init_db
from models.fund import Fund, FundHolding, FundNAV
from services.data.amfi_client import AMFIClient
from services.data.holdings_client import HoldingsClient
from services.data.mfapi_client import MFAPIClient
from services.data.sample_data import ensure_sample_holdings, generate_sample_portfolio_funds
from services.data.yfinance_client import YFinanceClient
from utils.logging_config import get_logger

logger = get_logger(__name__)


class FundService:
    """Facade for fund search, real NAV history, holdings, and health scores."""

    def __init__(self) -> None:
        self.amfi = AMFIClient()
        self.mfapi = MFAPIClient()
        self.holdings_client = HoldingsClient()
        self.yf = YFinanceClient()
        self.risk = RiskMetricsCalculator()
        self.scorer = FundHealthScorer()
        self._nav_cache: dict[str, pd.Series] = {}
        self._holdings_cache: dict[str, pd.DataFrame] = {}
        self._meta_enrich_cache: dict[str, dict[str, Any]] = {}
        self._nav_source: dict[str, str] = {}
        self._holdings_source: dict[str, str] = {}

    # Repaired once per process — reflection on every call would be wasteful.
    _schema_checked = False

    def ensure_db(self) -> None:
        settings.data_cache_dir.mkdir(parents=True, exist_ok=True)
        init_db()
        # create_all() never adds columns to an existing table, so a database
        # created before a model gained a field keeps the old shape and every
        # query on that field fails. Same defect that broke alerts and the
        # vault; the fund tables need the same repair.
        if not FundService._schema_checked:
            FundService._schema_checked = True
            try:
                from database import schema_repair
                from models.fund import Fund, FundDividend, FundHolding, FundMetric, FundNAV

                schema_repair.ensure_tables(
                    Fund.__table__,
                    FundNAV.__table__,
                    FundHolding.__table__,
                    FundMetric.__table__,
                    FundDividend.__table__,
                    label="funds",
                )
            except Exception as exc:
                logger.warning("Fund schema repair skipped: {}", exc)

    def sync_amfi_to_db(self, limit: Optional[int] = None, force: bool = False) -> int:
        """Upsert AMFI schemes into SQLite. Returns count upserted."""
        self.ensure_db()
        df = self.amfi.load(force_refresh=force)
        if limit:
            prefer = df[df["is_direct"] & df["is_growth"]].head(limit)
            if len(prefer) < limit:
                prefer = df.head(limit)
            df = prefer

        count = 0
        with SessionLocal() as db:
            for _, row in df.iterrows():
                code = str(row["amfi_code"])
                fund = db.query(Fund).filter(Fund.amfi_code == code).one_or_none()
                if fund is None:
                    fund = Fund(amfi_code=code, scheme_name=row["scheme_name"])
                    db.add(fund)
                fund.scheme_name = row["scheme_name"]
                fund.amc = row.get("amc")
                fund.category = row.get("category")
                fund.subcategory = row.get("subcategory")
                fund.isin_growth = row.get("isin_growth")
                fund.isin_div = row.get("isin_div")
                fund.latest_nav = float(row["nav"]) if pd.notna(row.get("nav")) else None
                nd = row.get("nav_date")
                if pd.notna(nd):
                    fund.nav_date = pd.to_datetime(nd).date() if not isinstance(nd, date) else nd
                count += 1
            db.commit()
        logger.info("Synced {} funds to DB", count)
        return count

    def search_funds(
        self,
        query: str = "",
        category: Optional[str] = None,
        limit: int = 50,
        direct_growth_only: bool = True,
    ) -> pd.DataFrame:
        try:
            df = self.amfi.load()
        except Exception as exc:
            logger.error("AMFI load failed: {}", exc)
            return generate_sample_portfolio_funds()

        if query:
            df = self.amfi.search(query, limit=500, direct_growth_only=False)
        if direct_growth_only and "is_direct" in df.columns:
            dg = df[df["is_direct"] & df["is_growth"]]
            if not dg.empty:
                df = dg
        if category and category != "All":
            df = df[df["category"] == category]
        return df.head(limit).reset_index(drop=True)

    def get_fund_meta(self, amfi_code: str, enrich: bool = False) -> dict[str, Any]:
        """Base meta from AMFI; optional enrichment from holdings provider."""
        row = self.amfi.get_by_code(amfi_code)
        if row is None:
            meta: dict[str, Any] = {"amfi_code": amfi_code, "scheme_name": "Unknown"}
        else:
            meta = row.to_dict()

        if enrich:
            extra = self.get_enriched_meta(str(amfi_code), meta.get("scheme_name"))
            for k, v in extra.items():
                if v is not None and v != "":
                    meta[k] = v
        return meta

    def get_enriched_meta(
        self, amfi_code: str, scheme_name: Optional[str] = None
    ) -> dict[str, Any]:
        """AUM, expense, manager, category detail from Groww (cached)."""
        code = str(amfi_code)
        if code in self._meta_enrich_cache:
            return self._meta_enrich_cache[code]
        try:
            bundle = self.holdings_client.get_scheme_bundle(code, scheme_name)
            meta = bundle.get("meta") or {}
            self._meta_enrich_cache[code] = meta
            return meta
        except Exception as exc:
            logger.info("Meta enrichment unavailable for {}: {}", code, exc)
            self._meta_enrich_cache[code] = {}
            return {}

    # ------------------------------------------------------------------ NAV
    def get_nav_history(
        self,
        amfi_code: str,
        scheme_name: Optional[str] = None,
        latest_nav: Optional[float] = None,
        years: float = 5.0,
        force_refresh: bool = False,
    ) -> pd.Series:
        """
        Historical NAV — real data from mfapi.in (TigZig fallback).

        Order: memory → disk/mfapi → SQLite → synthetic (optional last resort).
        """
        key = str(amfi_code)
        if not force_refresh and key in self._nav_cache:
            return self._trim_years(self._nav_cache[key], years)

        series: Optional[pd.Series] = None
        source = "unknown"

        # 1) Live / disk-cached historical NAV
        try:
            series = self.mfapi.get_nav_history(
                key, years=years, force_refresh=force_refresh
            )
            source = str(series.attrs.get("source") or "mfapi")
            logger.info(
                "NAV history for {} from {} ({} points)", key, source, len(series)
            )
            # Skip SQLite writes during bulk portfolio loads (keeps UI responsive)
            if settings.persist_nav_to_db and not getattr(self, "_bulk_skip_persist", False):
                self._persist_nav_series(key, scheme_name, series)
        except Exception as exc:
            logger.warning("Live NAV history failed for {}: {}", key, exc)

        # 2) SQLite historical rows
        if series is None or len(series) < 10:
            db_series = self._load_nav_from_db(key)
            if db_series is not None and len(db_series) >= 10:
                series = db_series
                source = "sqlite"
                logger.info("NAV history for {} from SQLite ({} points)", key, len(series))

        # 3) Synthetic fallback
        if series is None or len(series) < 10:
            if not settings.allow_synthetic_nav_fallback:
                raise RuntimeError(f"No historical NAV available for {key}")
            meta = self.get_fund_meta(key)
            name = scheme_name or meta.get("scheme_name") or key
            nav0 = latest_nav or meta.get("nav") or meta.get("latest_nav") or 100.0
            try:
                bench = self.yf.get_benchmark("NIFTY 50", period=f"{int(years)}y")
            except Exception:
                bench = None
            cat = (meta.get("subcategory") or meta.get("category") or "").lower()
            ret, vol, beta = self._category_vol(cat)
            series = self.yf.synthetic_fund_nav(
                name,
                latest_nav=float(nav0),
                years=years,
                annual_return=ret,
                annual_vol=vol,
                benchmark=bench,
                beta=beta,
                seed=int(key) if key.isdigit() else None,
            )
            source = "synthetic"
            series.attrs["source"] = "synthetic"
            logger.warning("Using SYNTHETIC NAV for {} — live providers failed", key)

        series.attrs["source"] = source
        series.attrs["amfi_code"] = key
        self._nav_cache[key] = series
        self._nav_source[key] = source
        return self._trim_years(series, years)

    def get_nav_source(self, amfi_code: str) -> str:
        return self._nav_source.get(str(amfi_code), "unknown")

    def _load_nav_from_db(self, amfi_code: str) -> Optional[pd.Series]:
        self.ensure_db()
        with SessionLocal() as db:
            fund = db.query(Fund).filter(Fund.amfi_code == str(amfi_code)).one_or_none()
            if not fund or not fund.navs:
                return None
            rows = sorted(fund.navs, key=lambda x: x.nav_date)
            s = pd.Series(
                {pd.Timestamp(r.nav_date): float(r.nav) for r in rows},
                name=fund.scheme_name,
            ).sort_index()
            s.attrs["source"] = "sqlite"
            s.attrs["amfi_code"] = str(amfi_code)
            return s if len(s) else None

    def _persist_nav_series(
        self,
        amfi_code: str,
        scheme_name: Optional[str],
        series: pd.Series,
    ) -> None:
        """Upsert NAV points into SQLite (sampled if extremely long to keep DB light)."""
        try:
            self.ensure_db()
            s = series.dropna().sort_index()
            # Cap storage: keep daily for last 3y, else weekly sample for older
            if len(s) > 900:
                recent_cut = s.index.max() - pd.DateOffset(years=3)
                recent = s[s.index >= recent_cut]
                older = s[s.index < recent_cut]
                if len(older):
                    older = older.resample("W-FRI").last().dropna()
                s = pd.concat([older, recent]).sort_index()
                s = s[~s.index.duplicated(keep="last")]

            with SessionLocal() as db:
                fund = self._get_or_create_fund(db, amfi_code, scheme_name)
                existing_dates = {
                    r.nav_date for r in db.query(FundNAV).filter(FundNAV.fund_id == fund.id).all()
                }
                added = 0
                for ts, nav in s.items():
                    d = pd.Timestamp(ts).date()
                    if d in existing_dates:
                        continue
                    db.add(FundNAV(fund_id=fund.id, nav_date=d, nav=float(nav)))
                    added += 1
                if len(s):
                    fund.latest_nav = float(s.iloc[-1])
                    fund.nav_date = pd.Timestamp(s.index[-1]).date()
                db.commit()
                if added:
                    logger.info("Persisted {} new NAV rows for {}", added, amfi_code)
        except Exception as exc:
            logger.warning("NAV persist failed for {}: {}", amfi_code, exc)

    # -------------------------------------------------------------- Holdings
    def get_holdings(
        self,
        amfi_code: str,
        scheme_name: Optional[str] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Portfolio holdings — Groww live data preferred, then SQLite, then sample.
        """
        key = str(amfi_code)
        if not force_refresh and key in self._holdings_cache:
            return self._holdings_cache[key].copy()

        df: Optional[pd.DataFrame] = None
        source = "unknown"

        # 1) Live Groww
        try:
            meta = self.get_fund_meta(key)
            name = scheme_name or meta.get("scheme_name")
            bundle = self.holdings_client.get_scheme_bundle(
                key, name, force_refresh=force_refresh
            )
            df = bundle["holdings"]
            if df is not None and not df.empty:
                source = str(bundle.get("source") or "groww")
                # Cache enriched meta
                self._meta_enrich_cache[key] = bundle.get("meta") or {}
                if settings.persist_holdings_to_db and not getattr(
                    self, "_bulk_skip_persist", False
                ):
                    self._persist_holdings(key, name, df, bundle.get("meta"))
                logger.info(
                    "Holdings for {} from {} ({} rows)", key, source, len(df)
                )
        except Exception as exc:
            logger.warning("Live holdings failed for {}: {}", key, exc)

        # 2) SQLite
        if df is None or df.empty:
            db_df = self._load_holdings_from_db(key)
            if db_df is not None and not db_df.empty:
                df = db_df
                source = "sqlite"
                logger.info("Holdings for {} from SQLite ({} rows)", key, len(df))

        # 3) Sample fallback
        if df is None or df.empty:
            if not settings.allow_sample_holdings_fallback:
                raise RuntimeError(f"No holdings available for {key}")
            meta = self.get_fund_meta(key)
            name = scheme_name or meta.get("scheme_name") or key
            cat = meta.get("subcategory") or meta.get("category") or "Flexi Cap"
            df = ensure_sample_holdings(key, name, str(cat))
            source = "sample"
            logger.warning("Using SAMPLE holdings for {} — live provider failed", key)

        self._holdings_cache[key] = df
        self._holdings_source[key] = source
        return df.copy()

    def get_holdings_source(self, amfi_code: str) -> str:
        return self._holdings_source.get(str(amfi_code), "unknown")

    def _load_holdings_from_db(self, amfi_code: str) -> Optional[pd.DataFrame]:
        self.ensure_db()
        with SessionLocal() as db:
            fund = db.query(Fund).filter(Fund.amfi_code == str(amfi_code)).one_or_none()
            if not fund or not fund.holdings:
                return None
            return pd.DataFrame(
                [
                    {
                        "security_name": h.security_name,
                        "isin": h.isin,
                        "sector": h.sector,
                        "market_cap": h.market_cap,
                        "weight_pct": h.weight_pct,
                        "country": h.country,
                        "asset_type": h.asset_type,
                        "as_of_date": h.as_of_date.isoformat() if h.as_of_date else None,
                    }
                    for h in fund.holdings
                ]
            )

    def _persist_holdings(
        self,
        amfi_code: str,
        scheme_name: Optional[str],
        holdings: pd.DataFrame,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        try:
            self.ensure_db()
            with SessionLocal() as db:
                fund = self._get_or_create_fund(db, amfi_code, scheme_name)
                # Replace holdings snapshot
                db.query(FundHolding).filter(FundHolding.fund_id == fund.id).delete()
                for _, r in holdings.iterrows():
                    as_of = None
                    if r.get("as_of_date"):
                        try:
                            as_of = pd.to_datetime(r["as_of_date"]).date()
                        except Exception:
                            as_of = date.today()
                    db.add(
                        FundHolding(
                            fund_id=fund.id,
                            security_name=str(r["security_name"]),
                            isin=r.get("isin"),
                            sector=r.get("sector"),
                            market_cap=r.get("market_cap"),
                            weight_pct=float(r["weight_pct"]),
                            country=r.get("country") or "India",
                            asset_type=r.get("asset_type") or "Equity",
                            as_of_date=as_of or date.today(),
                        )
                    )
                if meta:
                    if meta.get("expense_ratio") is not None:
                        fund.expense_ratio = float(meta["expense_ratio"])
                    if meta.get("aum_cr") is not None:
                        fund.aum_cr = float(meta["aum_cr"])
                    if meta.get("portfolio_turnover") is not None:
                        try:
                            fund.portfolio_turnover = float(meta["portfolio_turnover"])
                        except (TypeError, ValueError):
                            pass
                    if meta.get("fund_manager"):
                        fund.fund_manager = str(meta["fund_manager"])[:256]
                    if meta.get("benchmark"):
                        fund.benchmark = str(meta["benchmark"])[:256]
                    if meta.get("exit_load"):
                        fund.exit_load = str(meta["exit_load"])[:256]
                    if meta.get("equity_allocation") is not None:
                        fund.equity_allocation = float(meta["equity_allocation"])
                    if meta.get("debt_allocation") is not None:
                        fund.debt_allocation = float(meta["debt_allocation"])
                    if meta.get("cash_allocation") is not None:
                        fund.cash_allocation = float(meta["cash_allocation"])
                    if meta.get("international_exposure") is not None:
                        fund.international_exposure = float(meta["international_exposure"])
                fund.updated_at = datetime.utcnow()
                db.commit()
                logger.info("Persisted {} holdings for {}", len(holdings), amfi_code)
        except Exception as exc:
            logger.warning("Holdings persist failed for {}: {}", amfi_code, exc)

    def _get_or_create_fund(
        self, db: Session, amfi_code: str, scheme_name: Optional[str]
    ) -> Fund:
        fund = db.query(Fund).filter(Fund.amfi_code == str(amfi_code)).one_or_none()
        if fund is None:
            meta = self.get_fund_meta(amfi_code)
            fund = Fund(
                amfi_code=str(amfi_code),
                scheme_name=scheme_name or meta.get("scheme_name") or str(amfi_code),
                amc=meta.get("amc"),
                category=meta.get("category"),
                subcategory=meta.get("subcategory"),
                latest_nav=meta.get("nav") or meta.get("latest_nav"),
                source="amfi",
            )
            db.add(fund)
            db.flush()
        elif scheme_name and fund.scheme_name != scheme_name:
            fund.scheme_name = scheme_name
        return fund

    # ------------------------------------------------------------- Analytics
    def compute_fund_analytics(self, amfi_code: str) -> dict[str, Any]:
        meta = self.get_fund_meta(amfi_code)
        nav = self.get_nav_history(amfi_code, meta.get("scheme_name"), meta.get("nav"))
        holdings = self.get_holdings(amfi_code, meta.get("scheme_name"))
        enriched = self.get_enriched_meta(amfi_code, meta.get("scheme_name"))

        try:
            bench = self.yf.get_benchmark("NIFTY 50")
        except Exception:
            bench = None
        metrics = self.risk.compute(nav, bench)

        top10 = None
        n_hold = None
        if not holdings.empty and "weight_pct" in holdings.columns:
            w = holdings["weight_pct"].astype(float)
            top10 = float(w.nlargest(min(10, len(w))).sum())
            n_hold = len(holdings)

        expense = (
            enriched.get("expense_ratio")
            or meta.get("expense_ratio")
            or self._fallback_expense(amfi_code)
        )
        aum = enriched.get("aum_cr") or meta.get("aum_cr") or self._fallback_aum(amfi_code)
        tenure = meta.get("fund_manager_tenure_years")
        if tenure is None:
            tenure = self._fallback_tenure(amfi_code)
        manager = enriched.get("fund_manager") or meta.get("fund_manager")

        health = self.scorer.score(
            cagr=metrics.cagr,
            sharpe=metrics.sharpe,
            sortino=metrics.sortino,
            max_drawdown=metrics.max_drawdown,
            volatility=metrics.volatility,
            alpha=metrics.alpha,
            beta=metrics.beta,
            information_ratio=metrics.information_ratio,
            expense_ratio=expense,
            aum_cr=aum,
            manager_tenure_years=tenure,
            top10_concentration=top10,
            n_holdings=n_hold,
        )

        return {
            "meta": {**meta, **{k: v for k, v in enriched.items() if v is not None}},
            "metrics": metrics.to_dict(),
            "health": health.to_dict(),
            "nav": nav,
            "holdings": holdings,
            "expense_ratio": expense,
            "aum_cr": aum,
            "manager_tenure": tenure,
            "fund_manager": manager,
            "portfolio_turnover": enriched.get("portfolio_turnover")
            or meta.get("portfolio_turnover"),
            "data_sources": {
                "nav": self.get_nav_source(amfi_code) or nav.attrs.get("source"),
                "holdings": self.get_holdings_source(amfi_code),
                "meta_enrichment": "groww" if enriched else "amfi_only",
            },
        }

    def get_dividends(
        self, amfi_code: str, scheme_name: Optional[str] = None, years: float = 5.0
    ) -> tuple[list[dict[str, Any]], str]:
        """IDCW distribution history plus a note on how it was obtained.

        Returns ``(rows, note)``. Rows carry a ``source`` of ``provider`` or
        ``derived`` — see services.data.dividends. Callers must show the note;
        a derived figure is an estimate, not a reported payout.
        """
        from services.data.dividends import dividend_history

        code = str(amfi_code)
        name = scheme_name or self.get_fund_meta(code).get("scheme_name")
        detail = None
        try:
            detail = self.holdings_client.fetch_scheme_detail(
                self.holdings_client.resolve_search_id(code, name) or "", use_cache=True
            )
        except Exception:
            detail = None

        rows, note = dividend_history(
            self, code, name, years=years, provider_detail=detail
        )
        return [d.to_dict() for d in rows], note

    def seed_demo_holdings(self, amfi_codes: list[str]) -> None:
        """Force-refresh holdings for codes (live first)."""
        for code in amfi_codes:
            meta = self.get_fund_meta(code)
            try:
                self.get_holdings(
                    code, meta.get("scheme_name"), force_refresh=True
                )
            except Exception as exc:
                logger.warning("seed holdings failed for {}: {}", code, exc)

    def prefetch_fund(
        self, amfi_code: str, years: float = 5.0, force: bool = False
    ) -> dict[str, Any]:
        """Convenience: pull NAV + holdings + return sources."""
        meta = self.get_fund_meta(amfi_code)
        nav = self.get_nav_history(
            amfi_code, meta.get("scheme_name"), years=years, force_refresh=force
        )
        holdings = self.get_holdings(
            amfi_code, meta.get("scheme_name"), force_refresh=force
        )
        return {
            "amfi_code": amfi_code,
            "nav_points": len(nav),
            "nav_source": self.get_nav_source(amfi_code),
            "holdings_rows": len(holdings),
            "holdings_source": self.get_holdings_source(amfi_code),
            "nav_start": str(nav.index.min().date()) if len(nav) else None,
            "nav_end": str(nav.index.max().date()) if len(nav) else None,
        }

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _trim_years(series: pd.Series, years: float) -> pd.Series:
        if series is None or series.empty or years is None:
            return series
        cutoff = series.index.max() - pd.DateOffset(days=int(years * 365.25))
        out = series[series.index >= cutoff]
        for k, v in series.attrs.items():
            out.attrs[k] = v
        return out

    @staticmethod
    def _category_vol(cat: str) -> tuple[float, float, float]:
        if "small" in cat:
            return 0.15, 0.22, 1.1
        if "mid" in cat:
            return 0.14, 0.19, 1.05
        if "liquid" in cat or "debt" in cat or "overnight" in cat:
            return 0.065, 0.02, 0.05
        if "hybrid" in cat:
            return 0.10, 0.10, 0.7
        if "large" in cat:
            return 0.12, 0.14, 0.95
        return 0.12, 0.16, 0.95

    @staticmethod
    def _fallback_expense(amfi_code: str) -> float:
        code_i = int(amfi_code) if str(amfi_code).isdigit() else abs(hash(amfi_code)) % 10000
        return round(0.35 + (code_i % 120) / 100, 2)

    @staticmethod
    def _fallback_aum(amfi_code: str) -> float:
        code_i = int(amfi_code) if str(amfi_code).isdigit() else abs(hash(amfi_code)) % 10000
        return round(500 + (code_i * 17) % 40000, 1)

    @staticmethod
    def _fallback_tenure(amfi_code: str) -> float:
        code_i = int(amfi_code) if str(amfi_code).isdigit() else abs(hash(amfi_code)) % 10000
        return float(2 + (code_i % 12))
