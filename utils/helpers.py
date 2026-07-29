"""Generic helper functions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Optional


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Division that returns default when denominator is zero or NaN."""
    try:
        if denominator is None or denominator == 0:
            return default
        result = numerator / denominator
        if result != result:  # NaN
            return default
        return float(result)
    except (TypeError, ZeroDivisionError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Clamp a value into [low, high]."""
    return max(low, min(high, value))


def pct(value: float, decimals: int = 2) -> str:
    """Format as percentage string."""
    return f"{value * 100:.{decimals}f}%"


def format_inr(amount: float) -> str:
    """Format number in Indian rupee style (approx)."""
    if amount is None:
        return "—"
    abs_amt = abs(amount)
    sign = "-" if amount < 0 else ""
    if abs_amt >= 1e7:
        return f"{sign}₹{abs_amt / 1e7:.2f} Cr"
    if abs_amt >= 1e5:
        return f"{sign}₹{abs_amt / 1e5:.2f} L"
    return f"{sign}₹{abs_amt:,.2f}"


def to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def unique_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
