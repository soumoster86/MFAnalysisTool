"""IDCW / dividend history for a scheme.

Two paths, in order of trust:

1. **Provider-reported.** Groww's scheme detail carries a ``dividend`` field.
   Authoritative when present — but the search API only surfaces Direct Growth
   plans, and Growth plans never distribute, so in practice it is empty.

2. **Derived from NAV divergence.** An IDCW plan and its Growth sibling hold
   the same portfolio, so they earn the same return every day. When the IDCW
   plan's NAV falls materially further than the Growth plan's on the same day,
   the difference is a distribution — that is exactly what a payout looks like
   in NAV data.

The derived figure is an *estimate*. It is stored with ``source='derived'`` and
a confidence, and must be labelled as such wherever it is shown: presenting an
inferred number as a reported payout would be a fabrication.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Optional

import pandas as pd

from utils.logging_config import get_logger

logger = get_logger(__name__)

# A same-day divergence smaller than this is noise (rounding, a stale NAV
# print, marginally different expense accrual), not a distribution.
MIN_DIVERGENCE = 0.005  # 0.5% of NAV

# Above this the "sibling" is almost certainly not the same portfolio.
MAX_DIVERGENCE = 0.60


@dataclass
class Dividend:
    record_date: date
    amount_per_unit: float
    nav_before: Optional[float] = None
    nav_after: Optional[float] = None
    payout_type: str = "idcw"
    source: str = "derived"
    confidence: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["record_date"] = self.record_date.isoformat()
        return d


def _to_series(nav: Any) -> Optional[pd.Series]:
    if nav is None or not isinstance(nav, pd.Series) or nav.empty:
        return None
    s = nav.dropna().astype(float).sort_index()
    return s if len(s) > 2 else None


def from_provider(detail: Optional[dict[str, Any]]) -> list[Dividend]:
    """Parse a provider's reported dividend payload, if it has one."""
    if not detail:
        return []
    raw = detail.get("dividend")
    if not raw:
        return []
    rows = raw if isinstance(raw, list) else raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return []

    out: list[Dividend] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw_date = (
            item.get("record_date") or item.get("date") or item.get("ex_date")
        )
        raw_amount = (
            item.get("dividend") or item.get("amount") or item.get("dividend_per_unit")
        )
        if raw_date is None or raw_amount is None:
            continue
        try:
            parsed = pd.to_datetime(raw_date, dayfirst=True, errors="coerce")
            amount = float(raw_amount)
        except (TypeError, ValueError):
            continue
        if pd.isna(parsed) or amount <= 0:
            continue
        out.append(
            Dividend(
                record_date=parsed.date(),
                amount_per_unit=round(amount, 4),
                payout_type=str(item.get("type") or "idcw").lower(),
                source="provider",
                confidence=1.0,
            )
        )
    out.sort(key=lambda d: d.record_date, reverse=True)
    return out


def derive_from_navs(
    idcw_nav: pd.Series,
    growth_nav: pd.Series,
    *,
    min_divergence: float = MIN_DIVERGENCE,
) -> list[Dividend]:
    """Infer distributions from an IDCW plan diverging from its Growth sibling.

    Both plans hold the same portfolio, so on any day their returns should
    match. A day where the IDCW plan drops materially further is a payout of
    roughly that difference applied to the prior NAV.
    """
    idcw = _to_series(idcw_nav)
    growth = _to_series(growth_nav)
    if idcw is None or growth is None:
        return []

    joined = pd.DataFrame({"idcw": idcw, "growth": growth}).dropna()
    if len(joined) < 5:
        return []

    idcw_ret = joined["idcw"].pct_change()
    growth_ret = joined["growth"].pct_change()
    # Positive gap = IDCW fell further than Growth = distribution.
    gap = growth_ret - idcw_ret

    out: list[Dividend] = []
    prior_nav = joined["idcw"].shift(1)
    for ts, value in gap.items():
        if pd.isna(value) or value < min_divergence or value > MAX_DIVERGENCE:
            continue
        before = prior_nav.get(ts)
        after = joined["idcw"].get(ts)
        if before is None or pd.isna(before) or before <= 0:
            continue
        amount = float(value) * float(before)
        if amount <= 0:
            continue
        # Confidence scales with how far the gap clears the noise floor;
        # a 0.6% divergence is far less certain than a 6% one.
        confidence = min(1.0, float(value) / (min_divergence * 4))
        out.append(
            Dividend(
                record_date=pd.Timestamp(ts).date(),
                amount_per_unit=round(amount, 4),
                nav_before=round(float(before), 4),
                nav_after=round(float(after), 4) if after is not None else None,
                payout_type="idcw",
                source="derived",
                confidence=round(confidence, 3),
            )
        )
    out.sort(key=lambda d: d.record_date, reverse=True)
    return out


def is_idcw_plan(scheme_name: Optional[str]) -> bool:
    """True when the scheme name marks it as a payout (non-Growth) plan."""
    s = (scheme_name or "").lower()
    if "growth" in s and "idcw" not in s and "dividend" not in s:
        return False
    return any(tag in s for tag in ("idcw", "dividend", "payout", "income distribution"))


def growth_sibling_name(scheme_name: str) -> str:
    """The Growth-plan name corresponding to an IDCW scheme name."""
    import re

    out = re.sub(
        r"\b(idcw|dividend)\b(\s*(payout|reinvestment|option|plan))?",
        "Growth",
        scheme_name,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", out).strip()


# Words that describe the *plan*, not the fund. Two schemes are siblings when
# everything except these matches.
_PLAN_TOKENS = {
    "direct",
    "regular",
    "growth",
    "idcw",
    "dividend",
    "payout",
    "reinvestment",
    "option",
    "plan",
    "daily",
    "weekly",
    "fortnightly",
    "monthly",
    "quarterly",
    ""
    "half",
    "yearly",
    "annual",
}


def _base_tokens(scheme_name: str) -> frozenset[str]:
    """The fund's identity: name tokens with plan wording removed."""
    import re

    words = re.sub(r"[^a-z0-9 ]", " ", str(scheme_name or "").lower()).split()
    return frozenset(w for w in words if w and w not in _PLAN_TOKENS)


def _is_direct(scheme_name: str) -> bool:
    return "direct" in str(scheme_name or "").lower()


def find_growth_sibling(
    fund_service: Any, scheme_name: str, amfi_code: str
) -> Optional[dict[str, Any]]:
    """Locate the Growth plan holding the same portfolio as an IDCW scheme.

    AMFI scheme names carry irregular spacing and inconsistent plan wording, so
    a reconstructed full name will not match by substring. Compare the fund's
    identity tokens instead — everything except the plan words — and require
    the same Direct/Regular status, since a Direct-vs-Regular pair differs by
    TER and would drift apart for reasons that are not distributions.
    """
    want_tokens = _base_tokens(scheme_name)
    if not want_tokens:
        return None
    want_direct = _is_direct(scheme_name)

    # Search on the leading words, which are distinctive enough to shortlist
    # the fund family without depending on exact punctuation.
    probe = " ".join(str(scheme_name).split()[:4])
    try:
        df = fund_service.search_funds(probe, limit=200)
    except Exception as exc:
        logger.warning("Growth sibling search failed for {}: {}", amfi_code, exc)
        return None
    if df is None or df.empty:
        return None

    for _, row in df.iterrows():
        name = str(row.get("scheme_name") or "")
        code = str(row.get("amfi_code") or "")
        if not code or code == str(amfi_code):
            continue
        lowered = name.lower()
        if "growth" not in lowered or "idcw" in lowered or "dividend" in lowered:
            continue
        if _is_direct(name) != want_direct:
            continue
        if _base_tokens(name) != want_tokens:
            continue
        return {"amfi_code": code, "scheme_name": name}
    return None


def dividend_history(
    fund_service: Any,
    amfi_code: str,
    scheme_name: Optional[str] = None,
    *,
    years: float = 5.0,
    provider_detail: Optional[dict[str, Any]] = None,
) -> tuple[list[Dividend], str]:
    """Dividend history plus a note explaining where it came from."""
    reported = from_provider(provider_detail)
    if reported:
        return reported, "Reported by data provider."

    name = scheme_name or ""
    if not is_idcw_plan(name):
        return [], "Growth plan — distributes nothing by design."

    sibling = find_growth_sibling(fund_service, name, str(amfi_code))
    if not sibling:
        return [], (
            "No provider dividend data, and no matching Growth plan was found "
            "to derive distributions from."
        )

    try:
        idcw_nav = fund_service.get_nav_history(str(amfi_code), name, years=years)
        growth_nav = fund_service.get_nav_history(
            sibling["amfi_code"], sibling["scheme_name"], years=years
        )
    except Exception as exc:
        return [], f"Could not load NAV history to derive distributions: {exc}"

    # Deriving from a synthetic NAV path would manufacture payouts from noise.
    from services.data.provenance import FABRICATED, classify

    for code in (str(amfi_code), sibling["amfi_code"]):
        try:
            if classify(fund_service.get_nav_source(code)) == FABRICATED:
                return [], (
                    "NAV history for this plan or its Growth sibling is synthetic, "
                    "so distributions cannot be derived from it."
                )
        except Exception:
            pass

    derived = derive_from_navs(idcw_nav, growth_nav)
    note = (
        f"Estimated from NAV divergence against {sibling['scheme_name']} — "
        "these are inferred, not reported figures."
    )
    return derived, note
