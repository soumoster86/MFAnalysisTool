"""Alert evaluation engine — real NAV / portfolio rule checks (Slice B)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

from analytics.overlap import PortfolioOverlapAnalyzer
from analytics.risk_metrics import RiskMetricsCalculator
from services.alerts.rules import RuleSpec
from services.data.fund_service import FundService
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class FiredAlert:
    """Candidate alert produced by the engine (not yet persisted)."""

    alert_type: str
    severity: str
    title: str
    message: str
    amfi_code: Optional[str] = None
    scheme_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    fingerprint: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    rule_id: Optional[int] = None
    portfolio_id: Optional[int] = None


@dataclass
class EvalResult:
    fired: list[FiredAlert] = field(default_factory=list)
    checked_rules: int = 0
    checked_funds: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _today_key() -> str:
    return date.today().isoformat()


def _fingerprint(
    alert_type: str,
    *,
    amfi_code: str | None = None,
    portfolio_id: int | None = None,
    extra: str = "",
) -> str:
    scope = amfi_code or (f"p{portfolio_id}" if portfolio_id is not None else "global")
    return f"{alert_type}:{scope}:{extra}:{_today_key()}"


def _holding_weight(h: dict[str, Any], total: float) -> float:
    mv = h.get("market_value")
    inv = float(h.get("invested_amount") or 0)
    try:
        val = float(mv) if mv is not None else inv
    except (TypeError, ValueError):
        val = inv
    if total <= 0:
        return 0.0
    return max(val, 0.0) / total


def _portfolio_total(holdings: list[dict[str, Any]]) -> float:
    total = 0.0
    for h in holdings:
        mv = h.get("market_value")
        inv = float(h.get("invested_amount") or 0)
        try:
            total += float(mv) if mv is not None else inv
        except (TypeError, ValueError):
            total += inv
    return total


def _pnl_pct(h: dict[str, Any]) -> Optional[float]:
    inv = float(h.get("invested_amount") or 0)
    mv = h.get("market_value")
    units = float(h.get("units") or 0)
    nav = h.get("current_nav") or h.get("nav")
    if mv is None and units > 0 and nav is not None:
        try:
            mv = units * float(nav)
        except (TypeError, ValueError):
            mv = None
    if inv <= 0 or mv is None:
        return None
    try:
        return float(mv) / inv - 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


class AlertEngine:
    """
    Evaluate rule specs against portfolio holdings + live/cached NAV.

    Designed to run from Streamlit UI, FastAPI, or Celery without Redis.
    """

    def __init__(self, fund_service: Optional[FundService] = None) -> None:
        self.funds = fund_service or FundService()
        self.risk = RiskMetricsCalculator()
        self.overlap = PortfolioOverlapAnalyzer()
        # Avoid SQLite write storms during multi-fund eval
        self.funds._bulk_skip_persist = True  # type: ignore[attr-defined]

    def evaluate(
        self,
        holdings: list[dict[str, Any]],
        rules: list[RuleSpec],
        *,
        portfolio_id: Optional[int] = None,
        max_funds: int = 25,
        include_overlap: bool = True,
    ) -> EvalResult:
        result = EvalResult()
        active = [r for r in rules if r.enabled]
        result.checked_rules = len(active)
        if not holdings:
            result.skipped.append("No holdings to evaluate")
            return result

        # Prefer funds with AMFI codes; cap for latency
        coded = [h for h in holdings if str(h.get("amfi_code") or "").strip()]
        coded = coded[:max_funds]
        result.checked_funds = len(coded)

        fund_rules = [r for r in active if r.scope == "fund"]
        port_rules = [r for r in active if r.scope == "portfolio"]

        # ---- per-fund rules ----
        for h in coded:
            code = str(h.get("amfi_code")).strip()
            name = str(h.get("scheme_name") or code)
            # Optional rule filter by amfi_code
            applicable = [
                r
                for r in fund_rules
                if not r.amfi_code or str(r.amfi_code) == code
            ]
            if not applicable:
                continue

            nav: Optional[pd.Series] = None
            needs_nav = any(
                r.alert_type in ("nav_drop", "period_return", "drawdown") for r in applicable
            )
            if needs_nav:
                try:
                    nav = self.funds.get_nav_history(code, scheme_name=name, years=2.0)
                except Exception as exc:
                    result.errors.append(f"NAV {code}: {exc}")
                    nav = None

            for rule in applicable:
                try:
                    fired = self._eval_fund_rule(rule, h, code, name, nav, portfolio_id)
                    if fired:
                        result.fired.append(fired)
                except Exception as exc:
                    result.errors.append(f"{rule.alert_type}/{code}: {exc}")
                    logger.warning("Rule eval failed {} {}: {}", rule.alert_type, code, exc)

        # ---- portfolio-level rules ----
        for rule in port_rules:
            if rule.portfolio_id is not None and portfolio_id is not None:
                if rule.portfolio_id != portfolio_id:
                    continue
            try:
                if rule.alert_type == "concentration":
                    fired = self._eval_concentration(rule, holdings, portfolio_id)
                    if fired:
                        result.fired.extend(fired)
                elif rule.alert_type == "overlap" and include_overlap:
                    fired = self._eval_overlap(rule, coded, portfolio_id)
                    if fired:
                        result.fired.extend(fired)
            except Exception as exc:
                result.errors.append(f"{rule.alert_type}/portfolio: {exc}")
                logger.warning("Portfolio rule failed {}: {}", rule.alert_type, exc)

        return result

    # ------------------------------------------------------------------ fund
    def _eval_fund_rule(
        self,
        rule: RuleSpec,
        holding: dict[str, Any],
        code: str,
        name: str,
        nav: Optional[pd.Series],
        portfolio_id: Optional[int],
    ) -> Optional[FiredAlert]:
        t = rule.alert_type

        if t == "nav_drop":
            if nav is None or len(nav.dropna()) < 2:
                return None
            s = nav.dropna().astype(float).sort_index()
            daily = float(s.iloc[-1] / s.iloc[-2] - 1.0)
            if daily > rule.threshold:
                return None
            return FiredAlert(
                alert_type="nav_drop",
                severity=rule.severity,
                title=f"NAV drop {daily:.1%} — {name[:48]}",
                message=(
                    f"{name} moved {daily:.2%} on the latest session "
                    f"(threshold {rule.threshold:.1%})."
                ),
                amfi_code=code,
                scheme_name=name,
                metric_value=daily,
                threshold=rule.threshold,
                fingerprint=_fingerprint("nav_drop", amfi_code=code),
                payload={"daily_return": daily},
                rule_id=rule.id,
                portfolio_id=portfolio_id,
            )

        if t == "period_return":
            if nav is None or len(nav.dropna()) < 3:
                return None
            s = nav.dropna().astype(float).sort_index()
            lookback = max(int(rule.lookback_days or 5), 1)
            # Use calendar-ish lookback via last N trading points
            n = min(lookback, len(s) - 1)
            if n < 1:
                return None
            ret = float(s.iloc[-1] / s.iloc[-(n + 1)] - 1.0)
            if ret > rule.threshold:
                return None
            return FiredAlert(
                alert_type="period_return",
                severity=rule.severity,
                title=f"{lookback}d return {ret:.1%} — {name[:40]}",
                message=(
                    f"{name} returned {ret:.2%} over ~{lookback} sessions "
                    f"(threshold {rule.threshold:.1%})."
                ),
                amfi_code=code,
                scheme_name=name,
                metric_value=ret,
                threshold=rule.threshold,
                fingerprint=_fingerprint(
                    "period_return", amfi_code=code, extra=f"lb{lookback}"
                ),
                payload={"period_return": ret, "lookback_days": lookback},
                rule_id=rule.id,
                portfolio_id=portfolio_id,
            )

        if t == "drawdown":
            if nav is None or len(nav.dropna()) < 5:
                return None
            s = nav.dropna().astype(float).sort_index()
            years = max(int(rule.lookback_days or 365), 30) / 365.25
            # Trim roughly to lookback window if datetime index
            if isinstance(s.index, pd.DatetimeIndex):
                cutoff = s.index.max() - pd.Timedelta(days=int(rule.lookback_days or 365))
                s = s[s.index >= cutoff]
            if len(s) < 5:
                return None
            dd = self.risk.max_drawdown(s)
            # Current drawdown from peak (not just historical max) is more actionable
            peak = float(s.cummax().iloc[-1])
            current_dd = float(s.iloc[-1] / peak - 1.0) if peak else 0.0
            # Fire on either deep historical MDD or current DD breach
            metric = min(dd, current_dd)
            if metric > rule.threshold:
                return None
            return FiredAlert(
                alert_type="drawdown",
                severity=rule.severity,
                title=f"Drawdown {metric:.1%} — {name[:40]}",
                message=(
                    f"{name}: max drawdown {dd:.1%}, current from peak {current_dd:.1%} "
                    f"(threshold {rule.threshold:.1%})."
                ),
                amfi_code=code,
                scheme_name=name,
                metric_value=metric,
                threshold=rule.threshold,
                fingerprint=_fingerprint("drawdown", amfi_code=code),
                payload={
                    "max_drawdown": dd,
                    "current_drawdown": current_dd,
                    "lookback_days": rule.lookback_days,
                },
                rule_id=rule.id,
                portfolio_id=portfolio_id,
            )

        if t == "pnl":
            pnl = _pnl_pct(holding)
            if pnl is None:
                return None
            if pnl > rule.threshold:
                return None
            return FiredAlert(
                alert_type="pnl",
                severity=rule.severity,
                title=f"Unrealized P&L {pnl:.1%} — {name[:40]}",
                message=(
                    f"{name} unrealized return is {pnl:.1%} vs cost "
                    f"(threshold {rule.threshold:.1%})."
                ),
                amfi_code=code,
                scheme_name=name,
                metric_value=pnl,
                threshold=rule.threshold,
                fingerprint=_fingerprint("pnl", amfi_code=code),
                payload={"pnl": pnl},
                rule_id=rule.id,
                portfolio_id=portfolio_id,
            )

        return None

    # -------------------------------------------------------------- portfolio
    def _eval_concentration(
        self,
        rule: RuleSpec,
        holdings: list[dict[str, Any]],
        portfolio_id: Optional[int],
    ) -> list[FiredAlert]:
        total = _portfolio_total(holdings)
        if total <= 0:
            return []
        out: list[FiredAlert] = []
        for h in holdings:
            w = _holding_weight(h, total)
            if w < rule.threshold:
                continue
            code = str(h.get("amfi_code") or "") or None
            name = str(h.get("scheme_name") or code or "Holding")
            out.append(
                FiredAlert(
                    alert_type="concentration",
                    severity=rule.severity,
                    title=f"Concentration {w:.0%} — {name[:40]}",
                    message=(
                        f"{name} is {w:.1%} of portfolio value "
                        f"(threshold {rule.threshold:.0%})."
                    ),
                    amfi_code=code,
                    scheme_name=name,
                    metric_value=w,
                    threshold=rule.threshold,
                    fingerprint=_fingerprint(
                        "concentration",
                        amfi_code=code,
                        portfolio_id=portfolio_id,
                    ),
                    payload={"weight": w, "portfolio_total": total},
                    rule_id=rule.id,
                    portfolio_id=portfolio_id,
                )
            )
        return out

    def _eval_overlap(
        self,
        rule: RuleSpec,
        holdings: list[dict[str, Any]],
        portfolio_id: Optional[int],
    ) -> list[FiredAlert]:
        # Cap funds for holdings fetch (expensive)
        top = sorted(
            holdings,
            key=lambda h: float(h.get("market_value") or h.get("invested_amount") or 0),
            reverse=True,
        )[:8]
        if len(top) < 2:
            return []

        holdings_by_fund: dict[str, pd.DataFrame] = {}
        weights: dict[str, float] = {}
        total = _portfolio_total(top) or 1.0
        for h in top:
            code = str(h.get("amfi_code") or "").strip()
            name = str(h.get("scheme_name") or code)
            label = name[:40] or code
            try:
                df = self.funds.get_holdings(code, scheme_name=name)
            except Exception:
                df = None
            if df is None or (hasattr(df, "empty") and df.empty):
                continue
            holdings_by_fund[label] = df
            weights[label] = _holding_weight(h, total)

        if len(holdings_by_fund) < 2:
            return []

        ov = self.overlap.analyze(holdings_by_fund, weights)
        pairwise = ov.pairwise_overlap or {}
        out: list[FiredAlert] = []
        for pair, pct in pairwise.items():
            # analyzer may store 0-100 or 0-1
            val = float(pct)
            if val > 1.5:
                val = val / 100.0
            if val < rule.threshold:
                continue
            out.append(
                FiredAlert(
                    alert_type="overlap",
                    severity=rule.severity,
                    title=f"Overlap {val:.0%} — {str(pair)[:48]}",
                    message=(
                        f"Stock-level overlap {val:.1%} between {pair} "
                        f"(threshold {rule.threshold:.0%})."
                    ),
                    amfi_code=None,
                    scheme_name=str(pair)[:200],
                    metric_value=val,
                    threshold=rule.threshold,
                    fingerprint=_fingerprint(
                        "overlap",
                        portfolio_id=portfolio_id,
                        extra=str(pair)[:80],
                    ),
                    payload={"pair": pair, "overlap": val},
                    rule_id=rule.id,
                    portfolio_id=portfolio_id,
                )
            )
        # Also fire on overall holding_overlap if high
        overall = float(ov.holding_overlap_pct or 0)
        if overall > 1.5:
            overall = overall / 100.0
        if overall >= rule.threshold and not out:
            out.append(
                FiredAlert(
                    alert_type="overlap",
                    severity=rule.severity,
                    title=f"Portfolio stock overlap {overall:.0%}",
                    message=(
                        f"Effective portfolio stock overlap is {overall:.1%} "
                        f"(threshold {rule.threshold:.0%})."
                    ),
                    metric_value=overall,
                    threshold=rule.threshold,
                    fingerprint=_fingerprint("overlap", portfolio_id=portfolio_id, extra="overall"),
                    payload={"holding_overlap_pct": overall},
                    rule_id=rule.id,
                    portfolio_id=portfolio_id,
                )
            )
        return out
