"""Module 1 — Dashboard."""

from __future__ import annotations

import streamlit as st

from frontend.components.charts import (
    allocation_pie,
    drawdown_chart,
    gauge_score,
    line_nav,
    treemap_alloc,
)
from frontend.state import get_cached_analysis, init_portfolio_holdings
from frontend.theme import apply_theme, score_class
from utils.helpers import format_inr, pct

apply_theme()

st.markdown(
    """
    <div class="hero-banner">
      <h1>Portfolio Command Center</h1>
      <p>Live AMFI NAVs · Real history · Health, risk & allocation at a glance</p>
    </div>
    """,
    unsafe_allow_html=True,
)

src = st.session_state.get("portfolio_source")
if src == "mfcentral_cas":
    st.caption("📂 Portfolio source: **MFCentral CAS upload** (large portfolios use fast analysis)")
elif src == "vault":
    st.caption("📂 Portfolio source: **Saved vault** — reopen from My Portfolios anytime")
else:
    st.caption(
        "Tip: sign in → upload CAS → **Save to vault**, or open **My Portfolios** to load a saved set."
    )

holdings = init_portfolio_holdings()
n_funds = len([h for h in holdings if h.get("amfi_code")])
mode = "fast" if n_funds > 12 else "full"

c_left, c_right = st.columns([3, 1])
with c_right:
    force = st.button("Refresh analysis", help="Re-run even if cached")
    if n_funds > 12:
        want_full = st.checkbox("Deep analysis (slower)", value=False,
                                help="Loads stock holdings & fuller NAV history")
        if want_full:
            mode = "full"

progress = st.progress(0, text="Starting…")
status = st.empty()

def _progress(p: float, msg: str) -> None:
    progress.progress(min(1.0, max(0.0, p)), text=msg)
    status.caption(msg)

try:
    analysis = get_cached_analysis(
        holdings, mode=mode, force=force, progress=_progress
    )
except Exception as exc:
    progress.empty()
    st.error(f"Analysis failed: {exc}")
    st.stop()
else:
    progress.empty()
    status.empty()
    if analysis.mode == "fast":
        st.info(
            f"Fast analysis for **{n_funds}** schemes (top funds for risk charts). "
            "Enable **Deep analysis** for stock holdings & overlap detail.",
            icon="⚡",
        )

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Portfolio Value", format_inr(analysis.total_current))
c2.metric(
    "Overall P&L",
    format_inr(analysis.overall_gain),
    delta=pct(analysis.overall_gain_pct),
)
c3.metric(
    "Daily P&L",
    format_inr(analysis.daily_pnl),
    delta=pct(analysis.daily_pnl_pct),
)
c4.metric("Invested", format_inr(analysis.total_invested))
score = analysis.health_score
c5.markdown(
    f"**Health Score**<br><span class='score-pill {score_class(score)}'>{score:.0f}/100</span>",
    unsafe_allow_html=True,
)

st.markdown("---")
left, right = st.columns([1.2, 1])
with left:
    if analysis.nav_series is not None and len(analysis.nav_series) > 2:
        st.plotly_chart(line_nav(analysis.nav_series, "Portfolio Value Index"), use_container_width=True)
        st.plotly_chart(drawdown_chart(analysis.nav_series), use_container_width=True)
    else:
        st.info("Insufficient NAV history for charts.")

with right:
    st.plotly_chart(gauge_score(score, "Portfolio Health"), use_container_width=True)
    m1, m2, m3 = st.columns(3)
    m1.metric("CAGR", pct(analysis.portfolio_cagr or 0) if analysis.portfolio_cagr is not None else "—")
    m2.metric("Volatility", pct(analysis.volatility or 0) if analysis.volatility is not None else "—")
    m3.metric("Sharpe", f"{analysis.sharpe:.2f}" if analysis.sharpe is not None else "—")
    if analysis.max_drawdown is not None:
        st.metric("Max Drawdown", pct(analysis.max_drawdown))

st.subheader("Allocations")
a1, a2, a3 = st.columns(3)
with a1:
    st.plotly_chart(allocation_pie(analysis.asset_allocation, "Asset / Category"), use_container_width=True)
with a2:
    st.plotly_chart(treemap_alloc(analysis.sector_allocation, "Sector"), use_container_width=True)
with a3:
    st.plotly_chart(allocation_pie(analysis.market_cap_allocation, "Market Cap"), use_container_width=True)

st.subheader("Holdings")
st.dataframe(analysis.holdings_detail, use_container_width=True, hide_index=True)

with st.expander("Notes & methodology"):
    for n in analysis.notes:
        st.write(f"- {n}")
