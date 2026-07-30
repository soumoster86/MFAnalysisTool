"""Structured content for a portfolio report.

One model feeds the PDF, Excel and PowerPoint renderers so the three files say
the same thing in the same order. Without it each renderer picks its own
columns and rounding, and the same portfolio reads differently depending on
which button was pressed.

Values are carried as raw numbers *and* display strings: Excel wants the number
so its own cell formats and charts work, the PDF and deck want the formatted
text. Formatting a number twice in two places is how a report ends up quoting
two different figures for one holding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from services.data.provenance import Provenance
from utils.helpers import format_inr, pct

# Holdings columns worth showing, in reading order. The analysis carries more
# (internal ids, intermediate values) that belong nowhere near a client report.
HOLDING_COLUMNS: list[tuple[str, str, str]] = [
    ("scheme_name", "Scheme", "text"),
    ("category", "Category", "text"),
    ("units", "Units", "number"),
    ("invested_amount", "Invested", "money"),
    ("current_value", "Current value", "money"),
    ("gain", "Gain / loss", "money"),
    ("gain_pct", "Return", "percent"),
    ("weight_pct", "Weight", "percent_points"),
]


def _fmt(value: Any, kind: str) -> str:
    if value is None:
        return "—"
    try:
        if kind == "money":
            return format_inr(float(value))
        if kind == "percent":
            return pct(float(value), 1)
        if kind == "percent_points":
            return f"{float(value):.1f}%"
        if kind == "number":
            return f"{float(value):,.3f}"
        if kind == "ratio":
            return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)
    return str(value)


def _merge_label_variants(mapping: dict[str, float]) -> dict[str, float]:
    """Combine buckets that differ only by pluralisation or spacing.

    Holdings providers are inconsistent, so the same sector arrives as both
    "Financial" and "Financials" and the report shows one exposure twice. Only
    exact singular/plural pairs are merged — "Consumer" and "Consumer
    Discretionary" are genuinely different buckets and must stay apart.
    """
    totals: dict[str, float] = {}
    # Display label per merge key, preferring the longer spelling: "Financials"
    # reads better than "Financial", and plural is the usual provider form.
    labels: dict[str, str] = {}
    for label, weight in mapping.items():
        clean = " ".join(str(label).split())
        key = clean.lower().rstrip("s")
        totals[key] = totals.get(key, 0.0) + float(weight)
        if key not in labels or len(clean) > len(labels[key]):
            labels[key] = clean
    return {labels[key]: round(total, 2) for key, total in totals.items()}


@dataclass
class KPI:
    label: str
    value: str
    caption: str = ""
    # Sentiment so each renderer can colour it the same way.
    tone: str = "neutral"  # good | bad | neutral


@dataclass
class Section:
    """A titled block of rows: (label, formatted value)."""

    title: str
    rows: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""


@dataclass
class ReportData:
    title: str
    subtitle: str
    generated_at: datetime

    kpis: list[KPI] = field(default_factory=list)
    holdings: list[dict[str, Any]] = field(default_factory=list)
    holdings_display: list[dict[str, str]] = field(default_factory=list)
    allocations: dict[str, dict[str, float]] = field(default_factory=dict)
    risk: Section = field(default_factory=lambda: Section("Risk & return"))
    top_holdings: list[tuple[str, float]] = field(default_factory=list)
    overlap_rows: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ai_summary: str = ""
    data_warning: str = ""
    source_rows: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_warning(self) -> bool:
        return bool(self.data_warning)


def build_report_data(
    analysis: Any,
    *,
    title: str = "Portfolio Analysis Report",
    subtitle: str = "",
    ai_summary: str = "",
    max_holdings: int = 40,
) -> ReportData:
    """Turn a PortfolioAnalysis into everything the renderers need."""
    now = datetime.now()
    gain_tone = "good" if (analysis.overall_gain or 0) >= 0 else "bad"
    day_tone = "good" if (analysis.daily_pnl or 0) >= 0 else "bad"

    score = analysis.health_score or 0
    score_tone = "good" if score >= 65 else "bad" if score < 45 else "neutral"

    data = ReportData(
        title=title,
        subtitle=subtitle or f"Generated {now:%d %b %Y at %H:%M}",
        generated_at=now,
        kpis=[
            KPI("Portfolio value", format_inr(analysis.total_current), "Current market value"),
            KPI("Invested", format_inr(analysis.total_invested), "Total cost"),
            KPI(
                "Overall P&L",
                format_inr(analysis.overall_gain),
                pct(analysis.overall_gain_pct or 0, 1),
                gain_tone,
            ),
            KPI(
                "Day change",
                format_inr(analysis.daily_pnl),
                pct(analysis.daily_pnl_pct or 0, 2),
                day_tone,
            ),
            KPI("Health score", f"{score:.0f}/100", "Blended fund quality", score_tone),
            KPI(
                "Schemes",
                str(len(analysis.holdings_detail or [])),
                f"{analysis.mode} analysis",
            ),
        ],
    )

    # ---- holdings ---------------------------------------------------------
    rows = sorted(
        analysis.holdings_detail or [],
        key=lambda r: -(r.get("current_value") or 0),
    )[:max_holdings]

    for row in rows:
        invested = row.get("invested_amount") or 0
        current = row.get("current_value") or 0
        enriched = dict(row)
        enriched["gain"] = current - invested
        enriched["gain_pct"] = (current / invested - 1) if invested else None
        data.holdings.append(enriched)
        data.holdings_display.append(
            {label: _fmt(enriched.get(key), kind) for key, label, kind in HOLDING_COLUMNS}
        )

    # ---- allocations ------------------------------------------------------
    for name, mapping in (
        ("Asset allocation", analysis.asset_allocation),
        ("Sector allocation", analysis.sector_allocation),
        ("Market cap allocation", analysis.market_cap_allocation),
    ):
        cleaned = _merge_label_variants(
            {
                str(k): float(v)
                for k, v in (mapping or {}).items()
                if v is not None and float(v) > 0.01
            }
        )
        if cleaned:
            data.allocations[name] = dict(
                sorted(cleaned.items(), key=lambda kv: -kv[1])[:12]
            )

    # ---- risk -------------------------------------------------------------
    data.risk = Section(
        "Risk & return",
        rows=[
            ("Portfolio CAGR", _fmt(analysis.portfolio_cagr, "percent")),
            ("Volatility (annualised)", _fmt(analysis.volatility, "percent")),
            ("Sharpe ratio", _fmt(analysis.sharpe, "ratio")),
            ("Maximum drawdown", _fmt(analysis.max_drawdown, "percent")),
            ("Health score", f"{score:.1f} / 100"),
        ],
        note=(
            "Sharpe is absent when volatility is too low for the ratio to mean "
            "anything, and metrics need enough NAV history to be stable."
        ),
    )

    # ---- top holdings (look-through) --------------------------------------
    data.top_holdings = [
        (str(h.get("security")), float(h.get("weight_pct") or 0))
        for h in (analysis.top_holdings or [])[:12]
        if h.get("security")
    ]

    # ---- overlap ----------------------------------------------------------
    overlap = analysis.overlap or {}
    if overlap:
        for key, label in (
            ("holding_overlap_pct", "Average holding overlap"),
            ("sector_overlap_pct", "Sector overlap"),
            ("diversification_score", "Diversification score"),
        ):
            value = overlap.get(key)
            if value is not None:
                suffix = " / 100" if key == "diversification_score" else "%"
                data.overlap_rows.append((label, f"{float(value):.1f}{suffix}"))
        # Worst-offending fund pairs, which is what actually prompts a change.
        pairs = sorted(
            (overlap.get("pairwise_overlap") or {}).items(),
            key=lambda kv: -float(kv[1] or 0),
        )[:5]
        for names, value in pairs:
            data.overlap_rows.append((str(names)[:70], f"{float(value or 0):.1f}%"))

    # ---- provenance -------------------------------------------------------
    # A file is read away from the app, so the disclosure has to be inside it.
    prov = Provenance.from_dict(getattr(analysis, "data_sources", None))
    if prov.has_fabricated:
        # Name only the kinds that actually occurred — "0 funds used synthetic
        # NAV and 2 used sample holdings" reads like a bug.
        parts = []
        if prov.fabricated_nav:
            n = len(prov.fabricated_nav)
            parts.append(f"{n} fund{'s' if n > 1 else ''} on a synthetic NAV path")
        if prov.fabricated_holdings:
            n = len(prov.fabricated_holdings)
            parts.append(f"{n} fund{'s' if n > 1 else ''} on sample holdings")
        data.data_warning = (
            f"This analysis used {' and '.join(parts)} because live data providers "
            "failed. Figures derived from them are illustrative and will not match "
            "published returns."
        )
    for label, source in list(prov.nav.items())[:25]:
        data.source_rows.append((label[:60], f"NAV: {source}"))
    for label, source in list(prov.holdings.items())[:25]:
        data.source_rows.append((label[:60], f"Holdings: {source}"))

    data.notes = list(analysis.notes or [])
    data.ai_summary = ai_summary or ""
    return data
