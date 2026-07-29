"""Fund attribute change detection — the Module 13 triggers that need history.

NAV-based alerts (drop, drawdown, P&L) read a time series that already exists.
The remaining roadmap triggers — manager change, expense ratio change, category
change, benchmark change, portfolio/holdings change, large holding change,
sector allocation change, risk increase — are *differences between two points
in time*, and nothing in the schema kept that history: `funds` is overwritten
in place on every refresh.

So this module captures its own snapshots (`FundSnapshot`) and fires by
comparing the newest against the previous one.

Two rules govern correctness here:

1. A change alert needs two real snapshots. The first capture for a fund
   establishes a baseline and must never fire — otherwise every fund alerts
   once on first sight.
2. A snapshot built from fabricated data (synthetic NAV / sample holdings)
   must never be compared. Sample holdings are generated per-fund, so
   comparing them produces confident, entirely meaningless "holdings changed"
   alerts. See services.data.provenance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from services.data.provenance import FABRICATED, classify
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Attribute changes that are categorical — any difference fires, threshold is
# not meaningful. Mapped to (alert_type, severity, human label).
CATEGORICAL_CHANGES = {
    "fund_manager": ("manager_change", "critical", "Fund manager"),
    "category": ("category_change", "warning", "Category"),
    "subcategory": ("category_change", "warning", "Sub-category"),
    "benchmark": ("benchmark_change", "warning", "Benchmark"),
    "riskometer": ("risk_increase", "warning", "Riskometer"),
}

# Riskometer ordering, so we can tell an increase from a decrease.
RISKOMETER_ORDER = [
    "low",
    "low to moderate",
    "moderate",
    "moderately high",
    "high",
    "very high",
]


def _norm_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _riskometer_rank(value: Any) -> Optional[int]:
    s = (_norm_text(value) or "").lower()
    if not s:
        return None
    for i, level in enumerate(RISKOMETER_ORDER):
        if level == s:
            return i
    # Tolerate wording variants ("Very High Risk").
    for i, level in enumerate(RISKOMETER_ORDER):
        if level in s:
            return i
    return None


def _holdings_map(holdings: Optional[pd.DataFrame]) -> dict[str, float]:
    """{security_name: weight_pct} normalised to percent points."""
    if holdings is None or holdings.empty:
        return {}
    if "security_name" not in holdings.columns or "weight_pct" not in holdings.columns:
        return {}
    out: dict[str, float] = {}
    for _, row in holdings.iterrows():
        name = _norm_text(row.get("security_name"))
        if not name:
            continue
        try:
            w = float(row.get("weight_pct") or 0)
        except (TypeError, ValueError):
            continue
        # Some providers return fractions, others percent points.
        if 0 < w <= 1.5:
            w *= 100
        out[name] = out.get(name, 0.0) + w
    return out


def _sector_map(holdings: Optional[pd.DataFrame]) -> dict[str, float]:
    if holdings is None or holdings.empty:
        return {}
    if "sector" not in holdings.columns or "weight_pct" not in holdings.columns:
        return {}
    out: dict[str, float] = {}
    for _, row in holdings.iterrows():
        sec = _norm_text(row.get("sector")) or "Other"
        try:
            w = float(row.get("weight_pct") or 0)
        except (TypeError, ValueError):
            continue
        if 0 < w <= 1.5:
            w *= 100
        out[sec] = out.get(sec, 0.0) + w
    return out


def _hash_holdings(hmap: dict[str, float]) -> str:
    payload = json.dumps({k: round(v, 2) for k, v in sorted(hmap.items())}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class Snapshot:
    """In-memory form of a FundSnapshot row."""

    amfi_code: str
    scheme_name: Optional[str] = None
    captured_at: Optional[datetime] = None
    fund_manager: Optional[str] = None
    expense_ratio: Optional[float] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    benchmark: Optional[str] = None
    riskometer: Optional[str] = None
    aum_cr: Optional[float] = None
    volatility: Optional[float] = None
    holdings_count: Optional[int] = None
    holdings_hash: Optional[str] = None
    holdings: dict[str, float] = field(default_factory=dict)
    sectors: dict[str, float] = field(default_factory=dict)
    holdings_source: Optional[str] = None
    nav_source: Optional[str] = None

    @property
    def holdings_are_fabricated(self) -> bool:
        return classify(self.holdings_source) == FABRICATED

    @property
    def nav_is_fabricated(self) -> bool:
        return classify(self.nav_source) == FABRICATED

    def to_row(self) -> dict[str, Any]:
        """Column values for the FundSnapshot ORM row."""
        return {
            "amfi_code": self.amfi_code,
            "scheme_name": self.scheme_name,
            "fund_manager": self.fund_manager,
            "expense_ratio": self.expense_ratio,
            "category": self.category,
            "subcategory": self.subcategory,
            "benchmark": self.benchmark,
            "riskometer": self.riskometer,
            "aum_cr": self.aum_cr,
            "volatility": self.volatility,
            "holdings_count": self.holdings_count,
            "holdings_hash": self.holdings_hash,
            "holdings_json": json.dumps({k: round(v, 3) for k, v in self.holdings.items()}),
            "sector_json": json.dumps({k: round(v, 3) for k, v in self.sectors.items()}),
            "holdings_source": self.holdings_source,
            "nav_source": self.nav_source,
        }

    @classmethod
    def from_row(cls, row: Any) -> "Snapshot":
        def _load(raw: Any) -> dict[str, float]:
            try:
                data = json.loads(raw or "{}")
                return {str(k): float(v) for k, v in data.items()}
            except Exception:
                return {}

        return cls(
            amfi_code=str(row.amfi_code),
            scheme_name=row.scheme_name,
            captured_at=row.captured_at,
            fund_manager=row.fund_manager,
            expense_ratio=row.expense_ratio,
            category=row.category,
            subcategory=row.subcategory,
            benchmark=row.benchmark,
            riskometer=row.riskometer,
            aum_cr=row.aum_cr,
            volatility=row.volatility,
            holdings_count=row.holdings_count,
            holdings_hash=row.holdings_hash,
            holdings=_load(row.holdings_json),
            sectors=_load(row.sector_json),
            holdings_source=row.holdings_source,
            nav_source=row.nav_source,
        )


def build_snapshot(
    fund_service: Any,
    amfi_code: str,
    scheme_name: Optional[str] = None,
    *,
    include_holdings: bool = True,
    include_volatility: bool = True,
) -> Snapshot:
    """Capture a fund's current mutable attributes.

    Never raises for a partial fetch — a snapshot with some fields missing is
    still useful, and a missing field simply cannot produce a change alert.
    """
    code = str(amfi_code).strip()
    snap = Snapshot(amfi_code=code, scheme_name=_norm_text(scheme_name))

    try:
        meta = fund_service.get_fund_meta(code, enrich=True)
    except Exception as exc:
        logger.warning("Snapshot meta failed for {}: {}", code, exc)
        meta = {}

    snap.scheme_name = snap.scheme_name or _norm_text(meta.get("scheme_name"))
    snap.fund_manager = _norm_text(meta.get("fund_manager"))
    snap.category = _norm_text(meta.get("category"))
    snap.subcategory = _norm_text(meta.get("subcategory"))
    snap.benchmark = _norm_text(meta.get("benchmark"))
    snap.riskometer = _norm_text(meta.get("riskometer"))
    for field_name, key in (("expense_ratio", "expense_ratio"), ("aum_cr", "aum_cr")):
        try:
            raw = meta.get(key)
            setattr(snap, field_name, float(raw) if raw is not None else None)
        except (TypeError, ValueError):
            setattr(snap, field_name, None)

    if include_holdings:
        try:
            hdf = fund_service.get_holdings(code, snap.scheme_name)
            snap.holdings = _holdings_map(hdf)
            snap.sectors = _sector_map(hdf)
            snap.holdings_count = len(snap.holdings) or None
            snap.holdings_hash = _hash_holdings(snap.holdings) if snap.holdings else None
        except Exception as exc:
            logger.warning("Snapshot holdings failed for {}: {}", code, exc)
        try:
            snap.holdings_source = fund_service.get_holdings_source(code)
        except Exception:
            snap.holdings_source = "unknown"

    if include_volatility:
        try:
            nav = fund_service.get_nav_history(code, scheme_name=snap.scheme_name, years=1.0)
            if nav is not None and len(nav.dropna()) > 20:
                from analytics.risk_metrics import RiskMetricsCalculator

                risk = RiskMetricsCalculator()
                snap.volatility = risk.annualized_vol(risk.nav_to_returns(nav))
        except Exception as exc:
            logger.warning("Snapshot volatility failed for {}: {}", code, exc)
        try:
            snap.nav_source = fund_service.get_nav_source(code)
        except Exception:
            snap.nav_source = "unknown"

    return snap


@dataclass
class Change:
    """One detected difference, ready to become a FiredAlert."""

    alert_type: str
    severity: str
    title: str
    message: str
    amfi_code: str
    scheme_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    payload: dict[str, Any] = field(default_factory=dict)


def _thresholds(rules: Optional[list[Any]]) -> dict[str, float]:
    """Map alert_type -> threshold from enabled rule specs, with defaults.

    A non-positive threshold is ignored rather than honoured: the categorical
    rules carry threshold=0 because the field is meaningless to them, and
    letting a zero through on a magnitude type would fire on provider rounding
    noise (TER 1.0000 vs 1.0001) every single scan.
    """
    out = dict(DEFAULT_CHANGE_THRESHOLDS)
    for r in rules or []:
        if not getattr(r, "enabled", True):
            continue
        atype = getattr(r, "alert_type", None)
        if atype in out:
            try:
                value = abs(float(getattr(r, "threshold", 0) or 0))
            except (TypeError, ValueError):
                continue
            if value > 0:
                out[atype] = value
    return out


def _enabled_types(rules: Optional[list[Any]]) -> Optional[set[str]]:
    """Which change types the caller's rules allow; None means 'all'."""
    if rules is None:
        return None
    types = {
        getattr(r, "alert_type", None)
        for r in rules
        if getattr(r, "enabled", True)
    }
    types.discard(None)
    return types or None


DEFAULT_CHANGE_THRESHOLDS: dict[str, float] = {
    # Absolute change in expense ratio, percentage points (0.10 = 0.10pp).
    "expense_ratio_change": 0.10,
    # Fraction of the portfolio that turned over (0.20 = 20% by weight).
    "holdings_change": 0.20,
    # Weight change on a single security, percentage points (2.0 = 2pp).
    "large_holding_change": 2.0,
    # Weight change for any one sector, percentage points.
    "sector_shift": 5.0,
    # Relative increase in annualised volatility (0.25 = 25% higher).
    "risk_increase": 0.25,
}

CHANGE_ALERT_TYPES = [
    "manager_change",
    "expense_ratio_change",
    "category_change",
    "benchmark_change",
    "holdings_change",
    "large_holding_change",
    "sector_shift",
    "risk_increase",
]


def detect_changes(
    previous: Optional[Snapshot],
    current: Snapshot,
    *,
    rules: Optional[list[Any]] = None,
) -> list[Change]:
    """Differences between two snapshots of the same fund.

    Returns [] when `previous` is None — the first capture is a baseline, not
    a change — and skips any comparison whose inputs were fabricated.
    """
    if previous is None:
        return []
    if previous.amfi_code != current.amfi_code:
        raise ValueError(
            f"Cannot compare snapshots of different funds: "
            f"{previous.amfi_code} vs {current.amfi_code}"
        )

    thresholds = _thresholds(rules)
    allowed = _enabled_types(rules)

    def wanted(alert_type: str) -> bool:
        return allowed is None or alert_type in allowed

    name = current.scheme_name or previous.scheme_name or current.amfi_code
    changes: list[Change] = []

    # ---- categorical attribute changes -------------------------------------
    for attr, (alert_type, severity, label) in CATEGORICAL_CHANGES.items():
        if not wanted(alert_type):
            continue
        old = getattr(previous, attr, None)
        new = getattr(current, attr, None)
        # Only fire when both sides are known: None -> value is a metadata
        # backfill, not a real-world change.
        if old is None or new is None or old == new:
            continue

        if attr == "riskometer":
            old_rank, new_rank = _riskometer_rank(old), _riskometer_rank(new)
            # Only an *increase* in risk is an alert.
            if old_rank is None or new_rank is None or new_rank <= old_rank:
                continue

        changes.append(
            Change(
                alert_type=alert_type,
                severity=severity,
                title=f"{label} changed",
                message=f"{label} for {name} changed from “{old}” to “{new}”.",
                amfi_code=current.amfi_code,
                scheme_name=name,
                payload={"field": attr, "old": old, "new": new},
            )
        )

    # ---- expense ratio ------------------------------------------------------
    if (
        wanted("expense_ratio_change")
        and previous.expense_ratio is not None
        and current.expense_ratio is not None
    ):
        delta = current.expense_ratio - previous.expense_ratio
        if abs(delta) >= thresholds["expense_ratio_change"]:
            direction = "increased" if delta > 0 else "decreased"
            changes.append(
                Change(
                    alert_type="expense_ratio_change",
                    # A rising TER costs the investor money; a fall does not.
                    severity="warning" if delta > 0 else "info",
                    title=f"Expense ratio {direction}",
                    message=(
                        f"TER for {name} {direction} from {previous.expense_ratio:.2f}% "
                        f"to {current.expense_ratio:.2f}% ({delta:+.2f}pp)."
                    ),
                    amfi_code=current.amfi_code,
                    scheme_name=name,
                    metric_value=round(delta, 4),
                    threshold=thresholds["expense_ratio_change"],
                    payload={"old": previous.expense_ratio, "new": current.expense_ratio},
                )
            )

    # ---- holdings-derived changes ------------------------------------------
    # Sample holdings are synthesised per fund, so comparing them yields
    # confident nonsense. Skip the entire holdings family in that case.
    holdings_usable = (
        previous.holdings
        and current.holdings
        and not previous.holdings_are_fabricated
        and not current.holdings_are_fabricated
    )

    if holdings_usable:
        prev_h, cur_h = previous.holdings, current.holdings
        names = set(prev_h) | set(cur_h)

        # Portfolio change: total absolute weight turnover / 2, as a fraction
        # of the book. Normalise against the actual weight total rather than
        # assuming 100 — providers often return only the top N holdings, and
        # dividing by 100 would then badly under-report the turnover.
        turnover = sum(abs(cur_h.get(n, 0.0) - prev_h.get(n, 0.0)) for n in names) / 2.0
        base = max(sum(prev_h.values()), sum(cur_h.values()))
        turnover_frac = turnover / base if base > 0 else 0.0
        if wanted("holdings_change") and turnover_frac >= thresholds["holdings_change"]:
            added = sorted(n for n in cur_h if n not in prev_h)
            removed = sorted(n for n in prev_h if n not in cur_h)
            changes.append(
                Change(
                    alert_type="holdings_change",
                    severity="warning",
                    title="Portfolio holdings changed",
                    message=(
                        f"{name} turned over {turnover_frac:.1%} of its portfolio by weight "
                        f"({len(added)} added, {len(removed)} exited)."
                    ),
                    amfi_code=current.amfi_code,
                    scheme_name=name,
                    metric_value=round(turnover_frac, 4),
                    threshold=thresholds["holdings_change"],
                    payload={"added": added[:15], "removed": removed[:15]},
                )
            )

        # Large single-holding move.
        if wanted("large_holding_change"):
            moves = sorted(
                (
                    (n, cur_h.get(n, 0.0) - prev_h.get(n, 0.0))
                    for n in names
                ),
                key=lambda kv: -abs(kv[1]),
            )
            if moves and abs(moves[0][1]) >= thresholds["large_holding_change"]:
                sec, delta = moves[0]
                verb = "increased" if delta > 0 else "reduced"
                changes.append(
                    Change(
                        alert_type="large_holding_change",
                        severity="info",
                        title="Large holding change",
                        message=(
                            f"{name} {verb} its position in {sec} by {abs(delta):.2f}pp "
                            f"({prev_h.get(sec, 0.0):.2f}% → {cur_h.get(sec, 0.0):.2f}%)."
                        ),
                        amfi_code=current.amfi_code,
                        scheme_name=name,
                        metric_value=round(delta, 4),
                        threshold=thresholds["large_holding_change"],
                        payload={
                            "security": sec,
                            "old": prev_h.get(sec, 0.0),
                            "new": cur_h.get(sec, 0.0),
                            "others": [
                                {"security": s, "delta": round(d, 3)} for s, d in moves[1:6]
                            ],
                        },
                    )
                )

        # Sector allocation shift.
        if wanted("sector_shift") and previous.sectors and current.sectors:
            sectors = set(previous.sectors) | set(current.sectors)
            shifts = sorted(
                (
                    (s, current.sectors.get(s, 0.0) - previous.sectors.get(s, 0.0))
                    for s in sectors
                ),
                key=lambda kv: -abs(kv[1]),
            )
            if shifts and abs(shifts[0][1]) >= thresholds["sector_shift"]:
                sec, delta = shifts[0]
                verb = "increased" if delta > 0 else "decreased"
                changes.append(
                    Change(
                        alert_type="sector_shift",
                        severity="info",
                        title="Sector allocation shift",
                        message=(
                            f"{name} {verb} {sec} exposure by {abs(delta):.2f}pp "
                            f"({previous.sectors.get(sec, 0.0):.2f}% → "
                            f"{current.sectors.get(sec, 0.0):.2f}%)."
                        ),
                        amfi_code=current.amfi_code,
                        scheme_name=name,
                        metric_value=round(delta, 4),
                        threshold=thresholds["sector_shift"],
                        payload={
                            "sector": sec,
                            "shifts": [{"sector": s, "delta": round(d, 3)} for s, d in shifts[:6]],
                        },
                    )
                )

    # ---- risk increase (volatility) ----------------------------------------
    if (
        wanted("risk_increase")
        and previous.volatility
        and current.volatility
        and previous.volatility > 0
        and not previous.nav_is_fabricated
        and not current.nav_is_fabricated
    ):
        rel = current.volatility / previous.volatility - 1.0
        if rel >= thresholds["risk_increase"]:
            changes.append(
                Change(
                    alert_type="risk_increase",
                    severity="warning",
                    title="Risk increased",
                    message=(
                        f"Annualised volatility for {name} rose {rel:.1%} "
                        f"({previous.volatility:.1%} → {current.volatility:.1%})."
                    ),
                    amfi_code=current.amfi_code,
                    scheme_name=name,
                    metric_value=round(rel, 4),
                    threshold=thresholds["risk_increase"],
                    payload={"old": previous.volatility, "new": current.volatility},
                )
            )

    return changes
