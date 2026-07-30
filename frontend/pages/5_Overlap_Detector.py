"""Module 5 — Portfolio Overlap Detector (visual-first)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.overlap import PortfolioOverlapAnalyzer
from frontend.components.ui_blocks import (
    diversification_tone,
    horizontal_bar,
    insight_cards,
    overlap_level_tone,
    pairwise_overlap_heatmap,
    pairwise_overlap_table,
    tip_list,
    top_holdings_bar,
)
from frontend.components.provenance import provenance_for_codes, render_provenance
from frontend.state import get_fund_service, init_portfolio_holdings
from frontend.components.page import page_header
from frontend.theme import NEGATIVE, SERIES, apply_theme

apply_theme()

page_header(
    "Portfolio Overlap Detector",
    "See how much your funds share the same stocks — heatmap, concentrations, and plain-language tips.",
    "🔗",
)

holdings = init_portfolio_holdings()
if not holdings:
    st.warning("No portfolio holdings. Import a CAS or add funds in Portfolio Analyzer.")
    st.stop()

svc = get_fund_service()

# Large CAS portfolios: only analyze top N by value (UI stays responsive)
MAX_FUNDS_FOR_OVERLAP = 15
rows = []
for h in holdings:
    code = str(h.get("amfi_code") or "")
    if not code:
        continue
    val = float(h.get("market_value") or h.get("invested_amount") or 0)
    rows.append((val, h))
rows.sort(key=lambda x: -x[0])
if len(rows) > MAX_FUNDS_FOR_OVERLAP:
    st.warning(
        f"Portfolio has **{len(rows)}** schemes. Overlap is computed for the "
        f"**top {MAX_FUNDS_FOR_OVERLAP} by value** so the page stays responsive."
    )
    rows = rows[:MAX_FUNDS_FOR_OVERLAP]

holdings_by_fund = {}
fund_meta = {}
weights = {}

progress = st.progress(0, text="Loading fund holdings…")
total = max(len(rows), 1)
for i, (val, h) in enumerate(rows):
    code = str(h.get("amfi_code") or "")
    meta = svc.get_fund_meta(code)
    name = h.get("scheme_name") or meta.get("scheme_name") or code
    progress.progress((i + 1) / total, text=f"Holdings {i+1}/{total}: {str(name)[:40]}")
    try:
        holdings_by_fund[name] = svc.get_holdings(code, name)
    except Exception:
        holdings_by_fund[name] = __import__("pandas").DataFrame()
    fund_meta[name] = {"amc": meta.get("amc"), "category": meta.get("category")}
    weights[name] = float(h.get("invested_amount") or h.get("market_value") or val or 1)

progress.progress(1.0, text="Computing overlap…")
result = PortfolioOverlapAnalyzer().analyze(holdings_by_fund, weights, fund_meta)
progress.empty()

# Overlap is computed entirely from stock-level holdings, so sample holdings
# make every number here meaningless — disclose before any of it is shown.
render_provenance(
    provenance_for_codes(
        svc,
        entries=[
            (h.get("scheme_name") or str(h.get("amfi_code") or ""), str(h.get("amfi_code") or ""))
            for _, h in rows
        ],
    ),
    what="This overlap analysis",
)

# ---- KPI cards ----
insight_cards(
    [
        {
            "label": "Avg fund overlap",
            "value": f"{result.holding_overlap_pct:.1f}%",
            "help": "Average pairwise stock overlap across your funds",
            "tone": overlap_level_tone(result.holding_overlap_pct),
        },
        {
            "label": "Sector concentration",
            "value": f"{result.sector_overlap_pct:.1f}",
            "help": "Higher = sectors more concentrated",
            "tone": overlap_level_tone(result.sector_overlap_pct / 2),
        },
        {
            "label": "Diversification score",
            "value": f"{result.diversification_score:.0f}/100",
            "help": "Higher is better",
            "tone": diversification_tone(result.diversification_score),
        },
    ],
    cols=3,
)

# ---- Heatmap + ranked pairs ----
st.subheader("Pairwise fund overlap")
st.caption(
    "Dark green = little shared stock exposure · Yellow/orange = meaningful overlap · Red = high overlap. "
    "Diagonal is self (100%)."
)

if result.pairwise_overlap:
    st.plotly_chart(
        pairwise_overlap_heatmap(result.pairwise_overlap),
        use_container_width=True,
    )
    pair_df = pairwise_overlap_table(result.pairwise_overlap)
    with st.expander("Ranked pair table (easier to scan)", expanded=True):
        if not pair_df.empty:
            # Color-friendly level column
            st.dataframe(
                pair_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Overlap %": st.column_config.ProgressColumn(
                        "Overlap %",
                        min_value=0,
                        max_value=100,
                        format="%.1f%%",
                    ),
                    "Level": st.column_config.TextColumn("Level"),
                },
            )
            high = pair_df[pair_df["Overlap %"] >= 40]
            if not high.empty:
                st.warning(
                    f"**{len(high)}** fund pair(s) have high overlap (≥40%). "
                    "Those funds may not diversify each other much."
                )
else:
    st.info("Add at least two funds with holdings data to see pairwise overlap.")

# ---- Concentrations ----
st.subheader("Where money is concentrated")
c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(
        horizontal_bar(result.amc_concentration, "AMC concentration", color=SERIES[2]),
        use_container_width=True,
    )
with c2:
    st.plotly_chart(
        horizontal_bar(result.category_concentration, "Category concentration", color=SERIES[3]),
        use_container_width=True,
    )

# ---- Repeated stocks ----
st.subheader("Stocks repeated across funds")
st.caption("Same company appearing in multiple schemes increases true single-stock risk.")
if result.top_repeated_stocks:
    rep = pd.DataFrame(result.top_repeated_stocks)
    # Flatten funds list for display
    if "funds" in rep.columns:
        rep["Funds"] = rep["funds"].apply(
            lambda xs: ", ".join(
                (str(x)[:22] + "…") if len(str(x)) > 22 else str(x) for x in (xs or [])
            )
        )
        rep = rep.drop(columns=["funds"], errors="ignore")
    rename = {
        "security": "Stock",
        "fund_count": "# Funds",
        "portfolio_weight_pct": "Portfolio wt %",
    }
    rep = rep.rename(columns=rename)
    show_cols = [c for c in ["Stock", "# Funds", "Portfolio wt %", "Funds"] if c in rep.columns]
    st.dataframe(
        rep[show_cols] if show_cols else rep,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Portfolio wt %": st.column_config.ProgressColumn(
                "Portfolio wt %", min_value=0, max_value=max(15.0, float(rep["Portfolio wt %"].max() or 10)),
                format="%.2f%%",
            )
            if "Portfolio wt %" in rep.columns
            else None,
        },
    )
    # chart of top repeated by weight
    chart_data = {
        str(r.get("Stock") or r.get("security")): float(r.get("Portfolio wt %") or r.get("portfolio_weight_pct") or 0)
        for _, r in rep.head(12).iterrows()
    }
    if chart_data:
        st.plotly_chart(
            horizontal_bar(chart_data, "Top overlapping stocks by portfolio weight", color=NEGATIVE),
            use_container_width=True,
        )
else:
    st.success("No stocks appear in multiple funds — low name-level overlap.")

# ---- Tips ----
st.subheader("What this means")
tip_list(result.suggestions, title="")
