"""Module 4 — Portfolio Analyzer (visual-first)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.components.charts import correlation_heatmap, gauge_score, line_nav
from frontend.components.ui_blocks import (
    allocation_donut,
    diversification_tone,
    horizontal_bar,
    insight_cards,
    overlap_level_tone,
    pairwise_overlap_heatmap,
    score_pill,
    tip_list,
    top_holdings_bar,
)
from frontend.state import get_cached_analysis, init_portfolio_holdings, set_portfolio_holdings
from frontend.theme import apply_theme
from utils.helpers import format_inr, pct

apply_theme()

st.title("Portfolio Analyzer")
st.caption("Health, risk, allocations, and concentration — charts first, jargon second.")

st.page_link(
    "pages/16_Upload_CAS.py",
    label="Import holdings from MFCentral CAS PDF",
    icon="📤",
)
if st.session_state.get("portfolio_source") == "mfcentral_cas":
    st.success("Portfolio loaded from MFCentral CAS import.", icon="✅")

holdings = init_portfolio_holdings()
n_funds = len([h for h in holdings if h.get("amfi_code")])

with st.expander("Edit holdings", expanded=False):
    edited = st.data_editor(
        pd.DataFrame(holdings),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "amfi_code": st.column_config.TextColumn("AMFI Code"),
            "scheme_name": st.column_config.TextColumn("Scheme"),
            "invested_amount": st.column_config.NumberColumn("Invested ₹", min_value=0),
            "units": st.column_config.NumberColumn("Units", min_value=0),
            "sip_amount": st.column_config.NumberColumn("SIP ₹", min_value=0),
        },
    )
    if st.button("Apply holdings", type="primary"):
        rows = edited.fillna(0).to_dict(orient="records")
        set_portfolio_holdings(rows)
        st.success("Portfolio updated")
        st.rerun()

mode = "fast" if n_funds > 12 else "full"
ctrl1, ctrl2 = st.columns([1, 3])
with ctrl1:
    force = st.button("Refresh analysis")
with ctrl2:
    if n_funds > 12:
        if st.checkbox("Deep analysis (holdings + fuller history — slower)", value=False):
            mode = "full"
        else:
            st.caption(f"⚡ Fast mode for {n_funds} schemes — results are cached after the first run.")

progress = st.progress(0, text="Analyzing…")

def _progress(p: float, msg: str) -> None:
    progress.progress(min(1.0, max(0.0, p)), text=msg)

try:
    analysis = get_cached_analysis(
        init_portfolio_holdings(), mode=mode, force=force, progress=_progress
    )
except Exception as exc:
    progress.empty()
    st.error(f"Analysis failed: {exc}")
    st.stop()
else:
    progress.empty()
    if analysis.mode == "fast":
        st.info(
            "Showing **fast** portfolio view. Turn on **Deep analysis** for stock-level "
            "sectors, overlap heatmap, and more NAV history.",
            icon="⚡",
        )

# ---- Snapshot cards ----
insight_cards(
    [
        {
            "label": "Health score",
            "value": f"{analysis.health_score:.0f}/100",
            "help": "Blend of growth, risk, cost, quality",
            "tone": diversification_tone(analysis.health_score),
        },
        {
            "label": "Current value",
            "value": format_inr(analysis.total_current),
            "help": f"Invested {format_inr(analysis.total_invested)}",
            "tone": "neutral",
        },
        {
            "label": "Overall P&L",
            "value": format_inr(analysis.overall_gain),
            "help": pct(analysis.overall_gain_pct) if analysis.overall_gain_pct is not None else "",
            "tone": "good" if (analysis.overall_gain or 0) >= 0 else "bad",
        },
        {
            "label": "Risk (volatility)",
            "value": pct(analysis.volatility) if analysis.volatility is not None else "—",
            "help": f"CAGR {pct(analysis.portfolio_cagr) if analysis.portfolio_cagr else '—'} · "
            f"Sharpe {analysis.sharpe:.2f}" if analysis.sharpe is not None else "CAGR / Sharpe n/a",
            "tone": "warn" if (analysis.volatility or 0) > 0.18 else "neutral",
        },
    ],
    cols=4,
)

# ---- Charts row ----
tab_overview, tab_alloc, tab_risk, tab_overlap = st.tabs(
    ["Overview", "Allocations", "Risk & correlation", "Overlap snapshot"]
)

with tab_overview:
    c1, c2 = st.columns([1, 1.2])
    with c1:
        score_pill(analysis.health_score, "Portfolio health")
        st.plotly_chart(
            gauge_score(analysis.health_score, "Health"),
            use_container_width=True,
        )
    with c2:
        if analysis.nav_series is not None and len(analysis.nav_series) > 2:
            st.plotly_chart(
                line_nav(analysis.nav_series, "Portfolio value index (base 100)"),
                use_container_width=True,
            )
        else:
            st.info("Not enough history for a portfolio chart yet.")

    st.subheader("Scheme weights in your portfolio")
    if analysis.holdings_detail:
        weight_map = {
            str(r.get("scheme_name") or r.get("amfi_code")): float(r.get("weight_pct") or 0)
            for r in analysis.holdings_detail
        }
        st.plotly_chart(
            horizontal_bar(weight_map, "Weight by scheme", color="#58a6ff"),
            use_container_width=True,
        )
        # Readable table without raw dumps
        detail_df = pd.DataFrame(analysis.holdings_detail)
        show = [
            c
            for c in [
                "scheme_name",
                "category",
                "invested_amount",
                "current_value",
                "gain_pct",
                "weight_pct",
            ]
            if c in detail_df.columns
        ]
        if show:
            pretty = detail_df[show].copy()
            rename = {
                "scheme_name": "Scheme",
                "category": "Category",
                "invested_amount": "Invested ₹",
                "current_value": "Value ₹",
                "gain_pct": "Gain %",
                "weight_pct": "Weight %",
            }
            pretty = pretty.rename(columns=rename)
            if "Gain %" in pretty.columns:
                pretty["Gain %"] = pretty["Gain %"].apply(
                    lambda x: round(float(x) * 100, 2) if pd.notna(x) and abs(float(x)) <= 5 else round(float(x), 2)
                )
            st.dataframe(pretty, use_container_width=True, hide_index=True)

with tab_alloc:
    a1, a2, a3 = st.columns(3)
    with a1:
        st.plotly_chart(
            allocation_donut(analysis.asset_allocation, "By category / asset"),
            use_container_width=True,
        )
    with a2:
        st.plotly_chart(
            allocation_donut(analysis.sector_allocation, "By sector"),
            use_container_width=True,
        )
    with a3:
        st.plotly_chart(
            allocation_donut(analysis.market_cap_allocation, "By market cap"),
            use_container_width=True,
        )
    st.subheader("Top underlying stocks")
    if analysis.top_holdings:
        st.plotly_chart(
            top_holdings_bar(analysis.top_holdings, "Largest stock exposures"),
            use_container_width=True,
        )
        st.dataframe(
            pd.DataFrame(analysis.top_holdings).rename(
                columns={"security": "Stock", "weight_pct": "Weight %"}
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No underlying holdings available yet.")

with tab_risk:
    m1, m2, m3 = st.columns(3)
    m1.metric("CAGR", pct(analysis.portfolio_cagr) if analysis.portfolio_cagr is not None else "—")
    m2.metric("Volatility", pct(analysis.volatility) if analysis.volatility is not None else "—")
    m3.metric(
        "Max drawdown",
        pct(analysis.max_drawdown) if analysis.max_drawdown is not None else "—",
    )
    if analysis.correlation:
        st.subheader("How funds move together")
        st.caption("Values near 1 = funds often rise/fall together · near 0 = more independent.")
        corr_df = pd.DataFrame(analysis.correlation)
        # correlation_heatmap shortens labels uniquely (avoids DuplicateError)
        st.plotly_chart(
            correlation_heatmap(corr_df, "Fund return correlation"),
            use_container_width=True,
        )
    else:
        st.info("Correlation needs multiple funds with return history.")

with tab_overlap:
    if analysis.mode == "fast" and not analysis.overlap:
        st.info(
            "Stock-level overlap is skipped in **fast mode**. "
            "Enable **Deep analysis** above, or open the Overlap Detector "
            "(top 15 funds by value)."
        )
        st.page_link("pages/5_Overlap_Detector.py", label="Open Overlap Detector", icon="🔗")
    elif analysis.overlap:
        ov = analysis.overlap
        insight_cards(
            [
                {
                    "label": "Holding overlap",
                    "value": f"{ov.get('holding_overlap_pct', 0):.1f}%",
                    "help": "Average pairwise stock overlap",
                    "tone": overlap_level_tone(float(ov.get("holding_overlap_pct") or 0)),
                },
                {
                    "label": "Diversification",
                    "value": f"{ov.get('diversification_score', 0):.0f}/100",
                    "help": "Higher is better",
                    "tone": diversification_tone(float(ov.get("diversification_score") or 0)),
                },
                {
                    "label": "Top AMC share",
                    "value": (
                        f"{max((ov.get('amc_concentration') or {'_': 0}).values()):.0f}%"
                        if ov.get("amc_concentration")
                        else "—"
                    ),
                    "help": (
                        max(ov["amc_concentration"], key=ov["amc_concentration"].get)
                        if ov.get("amc_concentration")
                        else ""
                    ),
                    "tone": "warn",
                },
            ],
            cols=3,
        )
        if ov.get("pairwise_overlap"):
            st.plotly_chart(
                pairwise_overlap_heatmap(ov["pairwise_overlap"], "Overlap between funds"),
                use_container_width=True,
            )
        if ov.get("amc_concentration"):
            st.plotly_chart(
                horizontal_bar(ov["amc_concentration"], "AMC concentration", color="#d2a8ff"),
                use_container_width=True,
            )
        tip_list(ov.get("suggestions") or [], title="Overlap takeaways")
        st.page_link("pages/5_Overlap_Detector.py", label="Open full Overlap Detector", icon="🔗")
    else:
        st.info("Overlap snapshot unavailable.")

if analysis.notes:
    with st.expander("Methodology notes"):
        for n in analysis.notes:
            st.write(f"- {n}")
