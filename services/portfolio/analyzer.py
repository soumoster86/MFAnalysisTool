"""Portfolio-level analytics aggregation (fast path for large CAS imports)."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from analytics.health_score import FundHealthScorer
from analytics.overlap import PortfolioOverlapAnalyzer
from analytics.risk_metrics import RiskMetricsCalculator
from services.data.fund_service import FundService
from services.data.provenance import Provenance
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PortfolioAnalysis:
    total_invested: float
    total_current: float
    daily_pnl: float
    daily_pnl_pct: float
    overall_gain: float
    overall_gain_pct: float
    portfolio_cagr: Optional[float]
    expected_cagr: Optional[float]
    volatility: Optional[float]
    sharpe: Optional[float]
    max_drawdown: Optional[float]
    health_score: float
    asset_allocation: dict[str, float] = field(default_factory=dict)
    sector_allocation: dict[str, float] = field(default_factory=dict)
    market_cap_allocation: dict[str, float] = field(default_factory=dict)
    top_holdings: list[dict[str, Any]] = field(default_factory=list)
    correlation: Optional[dict[str, Any]] = None
    holdings_detail: list[dict[str, Any]] = field(default_factory=list)
    overlap: Optional[dict[str, Any]] = None
    nav_series: Optional[pd.Series] = None
    notes: list[str] = field(default_factory=list)
    mode: str = "full"
    # Which source fed each fund's NAV/holdings — see services.data.provenance.
    # Consumers must disclose fabricated inputs rather than presenting the
    # numbers as if they came from live market data.
    data_sources: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.nav_series is not None:
            d["nav_series"] = None
        return d


def holdings_fingerprint(holdings: list[dict[str, Any]], mode: str = "full") -> str:
    """Stable cache key for a portfolio + analysis mode."""
    slim = []
    for h in holdings:
        slim.append(
            {
                "c": str(h.get("amfi_code") or ""),
                "u": round(float(h.get("units") or 0), 4),
                "i": round(float(h.get("invested_amount") or 0), 2),
                "m": round(float(h.get("market_value") or 0), 2),
                "n": round(float(h.get("current_nav") or h.get("nav") or 0), 4),
            }
        )
    slim.sort(key=lambda x: x["c"])
    raw = json.dumps({"mode": mode, "h": slim}, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class PortfolioAnalyzerService:
    """
    Portfolio analytics.

    Modes
    -----
    fast  — large CAS-friendly: uses CAS market values when present, fetches NAV
            only for top funds, skips live stock holdings & heavy per-fund health.
    full  — deep analysis with holdings, overlap, and broader NAV coverage.
    auto  — fast if len(holdings) > threshold, else full.
    """

    FAST_THRESHOLD = 12
    MAX_NAV_FUNDS_FAST = 10
    MAX_NAV_FUNDS_FULL = 25
    MAX_HOLDINGS_FUNDS = 15
    MAX_HEALTH_FUNDS = 12
    NAV_WORKERS = 6

    def __init__(self, fund_service: Optional[FundService] = None) -> None:
        self.funds = fund_service or FundService()
        self.risk = RiskMetricsCalculator()
        self.scorer = FundHealthScorer()
        self.overlap = PortfolioOverlapAnalyzer()

    def analyze(
        self,
        holdings: list[dict[str, Any]],
        *,
        mode: str = "auto",
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> PortfolioAnalysis:
        if not holdings:
            return PortfolioAnalysis(
                0, 0, 0, 0, 0, 0, None, None, None, None, None, 0,
                notes=["No holdings provided."],
                mode=mode,
            )

        # Filter empty codes
        holdings = [h for h in holdings if str(h.get("amfi_code") or "").strip()]
        if mode == "auto":
            mode = "fast" if len(holdings) > self.FAST_THRESHOLD else "full"

        def report(p: float, msg: str) -> None:
            if progress:
                try:
                    progress(min(1.0, max(0.0, p)), msg)
                except Exception:
                    pass

        report(0.02, "Preparing portfolio lines…")
        detail = self._build_detail_rows(holdings)
        total_invested = sum(d["invested_amount"] for d in detail)
        total_current = sum(d["current_value"] for d in detail)
        for d in detail:
            d["weight_pct"] = (d["current_value"] / total_current * 100) if total_current else 0

        # Rank by value for selective deep fetch
        ranked = sorted(detail, key=lambda x: -x["current_value"])
        nav_limit = self.MAX_NAV_FUNDS_FAST if mode == "fast" else self.MAX_NAV_FUNDS_FULL
        nav_targets = ranked[:nav_limit]

        report(0.08, f"Fetching NAV history for top {len(nav_targets)} funds…")
        nav_map = self._fetch_navs_parallel(nav_targets, years=3.0 if mode == "fast" else 5.0)
        report(0.45, "Building portfolio return series…")

        port_nav, rets, corr = self._portfolio_series(detail, nav_map, total_current)
        metrics = self.risk.compute(port_nav) if len(port_nav) > 5 else None
        try:
            if metrics is not None and mode == "full":
                bench = self.funds.yf.get_benchmark("NIFTY 50")
                metrics = self.risk.compute(port_nav, bench)
        except Exception:
            pass

        # Category allocation always available (cheap)
        asset: dict[str, float] = {}
        for d in detail:
            cat = d.get("category") or d.get("subcategory") or "Other"
            asset[cat] = asset.get(cat, 0) + d["weight_pct"]

        sector: dict[str, float] = {}
        mcap: dict[str, float] = {}
        stock_w: dict[str, float] = {}
        holdings_by_fund: dict[str, pd.DataFrame] = {}
        fund_meta: dict[str, dict] = {}
        ov = None

        if mode == "full":
            hold_targets = ranked[: self.MAX_HOLDINGS_FUNDS]
            report(0.55, f"Loading stock holdings for top {len(hold_targets)} funds…")
            for d in hold_targets:
                name = d["scheme_name"]
                try:
                    hdf = self.funds.get_holdings(d["amfi_code"], name)
                    holdings_by_fund[name] = hdf
                except Exception as exc:
                    logger.warning("Holdings skip {}: {}", d["amfi_code"], exc)
                    holdings_by_fund[name] = pd.DataFrame()
                fund_meta[name] = {
                    "amc": d.get("amc"),
                    "category": d.get("category"),
                    "subcategory": d.get("subcategory"),
                }
                pw = d["weight_pct"] / 100.0
                hdf = holdings_by_fund.get(name)
                if hdf is None or hdf.empty:
                    continue
                for _, row in hdf.iterrows():
                    try:
                        wt = abs(float(row.get("weight_pct", 0)))
                    except (TypeError, ValueError):
                        continue
                    if wt > 1.5:
                        wt = wt  # already percent points
                    else:
                        wt = wt * 100
                    sec = str(row.get("sector") or "Other")
                    mc = str(row.get("market_cap") or "Other")
                    sn = str(row.get("security_name") or "Other")
                    sector[sec] = sector.get(sec, 0) + pw * wt
                    mcap[mc] = mcap.get(mc, 0) + pw * wt
                    stock_w[sn] = stock_w.get(sn, 0) + pw * wt

            report(0.75, "Computing fund overlap…")
            if len(holdings_by_fund) >= 2:
                # Cap pairwise cost: at most 12 funds
                names = list(holdings_by_fund.keys())[:12]
                slim_h = {n: holdings_by_fund[n] for n in names}
                slim_w = {d["scheme_name"]: d["current_value"] for d in detail if d["scheme_name"] in slim_h}
                slim_m = {n: fund_meta.get(n, {}) for n in names}
                ov = self.overlap.analyze(slim_h, slim_w, slim_m).to_dict()
        else:
            report(0.60, "Fast mode: category allocation only (skip stock holdings)…")

        top_holdings = sorted(
            [{"security": k, "weight_pct": round(v, 2)} for k, v in stock_w.items()],
            key=lambda x: -x["weight_pct"],
        )[:15]

        report(0.85, "Scoring portfolio health…")
        health_score = self._blend_health(ranked, mode=mode)

        daily_pnl = sum(d["daily_pnl"] for d in detail)
        overall_gain = total_current - total_invested

        notes = [
            f"Analysis mode: **{mode}** ({len(detail)} schemes).",
            "Current values prefer CAS market value / NAV×units, then AMFI NAV.",
        ]
        if mode == "fast":
            notes.append(
                f"Fast mode: NAV history for top {nav_limit} by value only; "
                "stock-level holdings & full overlap deferred (use Full analysis)."
            )
        else:
            notes.append(
                f"Full mode: holdings for top {self.MAX_HOLDINGS_FUNDS}, "
                f"NAV for top {nav_limit}, overlap on up to 12 funds."
            )
        if len(detail) > nav_limit:
            notes.append(
                f"Only the largest {nav_limit} funds feed portfolio risk charts "
                "(keeps the UI responsive)."
            )

        prov = Provenance.from_service(
            self.funds,
            [(d["scheme_name"], d["amfi_code"]) for d in detail],
        )
        if prov.has_fabricated:
            notes.append(
                f"⚠ {len(prov.fabricated_nav)} fund(s) used synthetic NAV and "
                f"{len(prov.fabricated_holdings)} used sample holdings — "
                "live providers failed for those."
            )

        report(1.0, "Done")
        return PortfolioAnalysis(
            total_invested=round(total_invested, 2),
            total_current=round(total_current, 2),
            daily_pnl=round(daily_pnl, 2),
            daily_pnl_pct=round(daily_pnl / total_current, 4) if total_current else 0,
            overall_gain=round(overall_gain, 2),
            overall_gain_pct=round(overall_gain / total_invested, 4) if total_invested else 0,
            portfolio_cagr=metrics.cagr if metrics else None,
            expected_cagr=metrics.cagr if metrics else None,
            volatility=metrics.volatility if metrics else None,
            sharpe=metrics.sharpe if metrics else None,
            max_drawdown=metrics.max_drawdown if metrics else None,
            health_score=round(health_score, 1),
            asset_allocation={k: round(v, 2) for k, v in sorted(asset.items(), key=lambda x: -x[1])},
            sector_allocation={k: round(v, 2) for k, v in sorted(sector.items(), key=lambda x: -x[1])[:12]},
            market_cap_allocation={k: round(v, 2) for k, v in sorted(mcap.items(), key=lambda x: -x[1])},
            top_holdings=top_holdings,
            correlation=corr,
            holdings_detail=detail,
            overlap=ov,
            nav_series=port_nav,
            notes=notes,
            mode=mode,
            data_sources=prov.to_dict(),
        )

    # ---------------------------------------------------------------- builders
    def _build_detail_rows(self, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        detail: list[dict[str, Any]] = []
        for h in holdings:
            code = str(h.get("amfi_code") or "").strip()
            if not code:
                continue
            try:
                meta = self.funds.get_fund_meta(code)
            except Exception:
                meta = {"amfi_code": code}
            name = h.get("scheme_name") or meta.get("scheme_name") or code
            invested = float(h.get("invested_amount") or 0)
            units = float(h.get("units") or 0)

            # Prefer CAS-provided valuation (avoids network for every line)
            cas_nav = h.get("current_nav") or h.get("nav")
            cas_mkt = h.get("market_value")
            amfi_nav = meta.get("nav") or meta.get("latest_nav")

            latest_nav = None
            for candidate in (cas_nav, amfi_nav, 100.0):
                if candidate is not None:
                    try:
                        latest_nav = float(candidate)
                        if latest_nav > 0:
                            break
                    except (TypeError, ValueError):
                        continue
            latest_nav = latest_nav or 100.0

            if cas_mkt is not None and float(cas_mkt) > 0:
                current = float(cas_mkt)
                if units <= 0 and latest_nav > 0:
                    units = current / latest_nav
            else:
                if units <= 0 and invested > 0 and latest_nav > 0:
                    units = invested / latest_nav
                current = float(units) * latest_nav

            if invested <= 0 and current > 0:
                invested = current  # demat CAS lines

            detail.append(
                {
                    "amfi_code": code,
                    "scheme_name": name,
                    "category": meta.get("category"),
                    "subcategory": meta.get("subcategory"),
                    "amc": meta.get("amc"),
                    "invested_amount": invested,
                    "units": float(units),
                    "current_nav": latest_nav,
                    "current_value": current,
                    "gain": current - invested,
                    "gain_pct": (current / invested - 1) if invested else 0,
                    "daily_ret": 0.0,
                    "daily_pnl": 0.0,
                    "weight_pct": 0.0,
                    "sip_amount": h.get("sip_amount") or 0,
                }
            )
        return detail

    def _fetch_navs_parallel(
        self, targets: list[dict[str, Any]], years: float = 3.0
    ) -> dict[str, pd.Series]:
        nav_map: dict[str, pd.Series] = {}
        if not targets:
            return nav_map

        # Temporarily avoid heavy SQLite writes during bulk load
        prev_persist = getattr(self.funds, "_bulk_skip_persist", False)
        self.funds._bulk_skip_persist = True  # type: ignore[attr-defined]

        def _one(d: dict[str, Any]) -> tuple[str, Optional[pd.Series], float]:
            code = d["amfi_code"]
            name = d["scheme_name"]
            try:
                nav = self.funds.get_nav_history(
                    code, name, d.get("current_nav"), years=years, force_refresh=False
                )
                daily = 0.0
                if nav is not None and len(nav) >= 2:
                    daily = float(nav.iloc[-1] / nav.iloc[-2] - 1)
                return name, nav, daily
            except Exception as exc:
                logger.warning("NAV fetch failed for {}: {}", code, exc)
                return name, None, 0.0

        try:
            with ThreadPoolExecutor(max_workers=self.NAV_WORKERS) as ex:
                futs = [ex.submit(_one, d) for d in targets]
                by_name_daily: dict[str, float] = {}
                for fut in as_completed(futs):
                    name, nav, daily = fut.result()
                    by_name_daily[name] = daily
                    if nav is not None and len(nav) > 5:
                        nav_map[name] = nav
            for d in targets:
                d["daily_ret"] = by_name_daily.get(d["scheme_name"], 0.0)
                d["daily_pnl"] = d["current_value"] * d["daily_ret"]
        finally:
            self.funds._bulk_skip_persist = prev_persist  # type: ignore[attr-defined]

        return nav_map

    def _portfolio_series(
        self,
        detail: list[dict[str, Any]],
        nav_map: dict[str, pd.Series],
        total_current: float,
    ) -> tuple[pd.Series, pd.DataFrame, Optional[dict]]:
        if not nav_map or total_current <= 0:
            return pd.Series(dtype=float), pd.DataFrame(), None

        rets = pd.DataFrame({k: v.pct_change() for k, v in nav_map.items()}).dropna(how="all")
        if rets.empty:
            return pd.Series(dtype=float), rets, None

        w = {d["scheme_name"]: d["current_value"] / total_current for d in detail}
        aligned_w = np.array([w.get(c, 0) for c in rets.columns], dtype=float)
        if aligned_w.sum() <= 0:
            aligned_w = np.ones(len(rets.columns)) / len(rets.columns)
        else:
            # Renormalize among funds that have NAV series
            aligned_w = aligned_w / aligned_w.sum()

        port_ret = rets.fillna(0).values @ aligned_w
        port_nav = pd.Series(100 * np.cumprod(1 + port_ret), index=rets.index, name="Portfolio")

        corr = None
        if rets.shape[1] > 1:
            # Limit correlation matrix size for UI
            cols = list(rets.columns)[:15]
            corr = rets[cols].corr().round(3).to_dict()
        return port_nav, rets, corr

    def _blend_health(self, ranked: list[dict[str, Any]], mode: str) -> float:
        """Weighted health without re-fetching full analytics for every fund."""
        if not ranked:
            return 50.0
        limit = self.MAX_HEALTH_FUNDS if mode == "full" else min(8, self.MAX_HEALTH_FUNDS)
        targets = ranked[:limit]
        total_w = sum(d["weight_pct"] for d in targets) or 1.0
        score = 0.0

        for d in targets:
            w = d["weight_pct"] / total_w
            cat = (d.get("subcategory") or d.get("category") or "").lower()
            base = 55.0
            if "small" in cat:
                base = 52.0
            elif "mid" in cat:
                base = 56.0
            elif "large" in cat or "flexi" in cat:
                base = 62.0
            elif "debt" in cat or "liquid" in cat or "bond" in cat or "money" in cat:
                base = 68.0
            elif "index" in cat or "etf" in cat:
                base = 70.0
            gain = d.get("gain_pct") or 0
            base += max(-10.0, min(10.0, float(gain) * 20))
            score += base * w
        return float(score)
