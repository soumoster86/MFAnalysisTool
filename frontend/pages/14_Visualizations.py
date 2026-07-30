"""Module 14 — Visualization gallery."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.components.charts import (
    allocation_pie,
    correlation_heatmap,
    drawdown_chart,
    efficient_frontier,
    line_nav,
    risk_return_scatter,
    sunburst_from_holdings,
    treemap_alloc,
)
from frontend.components.page import empty_state, page_header
from frontend.components.provenance import render_provenance
from frontend.components.ui_blocks import short_fund_name
from frontend.state import get_cached_analysis, get_fund_service, init_portfolio_holdings
from frontend.theme import apply_theme
from analytics.optimizer import PortfolioOptimizer

apply_theme()

page_header(
    "Visualization Lab",
    "Plotly · treemap · heatmap · sunburst · frontier · drawdown · risk-return",
    "📉",
)

holdings = init_portfolio_holdings()
svc = get_fund_service()

if not holdings:
    empty_state(
        "No portfolio loaded",
        "Import a CAS, open a saved portfolio, or add holdings on the Dashboard.",
        icon="📈",
    )
    st.stop()

n_funds = len([h for h in holdings if h.get("amfi_code")])
c1, c2 = st.columns([1, 3])
with c1:
    force = st.button("Refresh", use_container_width=True)
with c2:
    deep = st.checkbox(
        "Deep analysis",
        value=n_funds <= 12,
        help=(
            "Fetches stock-level holdings so sector charts and look-through "
            "weights are available. Slower on large portfolios."
        ),
    )

# Previously this called analyze() directly, so every tab click re-ran the
# whole analysis; the cache keys on the holdings and mode.
try:
    analysis = get_cached_analysis(
        holdings, mode="full" if deep else "fast", force=force
    )
except Exception as exc:
    st.error(f"Analysis failed: {exc}")
    st.stop()

render_provenance(analysis.data_sources, what="These charts")

tab1, tab2, tab3, tab4 = st.tabs(["Portfolio", "Holdings", "Risk", "Frontier"])

with tab1:
    if analysis.nav_series is not None and len(analysis.nav_series) > 2:
        st.plotly_chart(line_nav(analysis.nav_series), use_container_width=True)
        st.plotly_chart(drawdown_chart(analysis.nav_series), use_container_width=True)
    c1, c2 = st.columns(2)
    c1.plotly_chart(treemap_alloc(analysis.sector_allocation, "Sector Treemap"), use_container_width=True)
    c2.plotly_chart(allocation_pie(analysis.asset_allocation, "Asset Pie"), use_container_width=True)

with tab2:
    if not analysis.holdings_detail:
        empty_state(
            "No holdings loaded",
            "Import a CAS or open a saved portfolio to chart what your funds hold.",
            icon="🗂️",
        )
    else:
        # The sunburst shows one fund's book. It previously rendered the first
        # holding with its centre labelled "Portfolio", which read as a
        # look-through of everything — pick the fund explicitly instead.
        by_value = sorted(
            analysis.holdings_detail,
            key=lambda r: -(r.get("current_value") or 0),
        )
        choices = {
            f"{(r.get('scheme_name') or r['amfi_code'])[:52]}": str(r["amfi_code"])
            for r in by_value
        }
        picked = st.selectbox("Show holdings of", list(choices), key="viz_sunburst_fund")
        code = choices[picked]

        with st.spinner("Loading holdings…"):
            hdf = svc.get_holdings(code)
        st.plotly_chart(
            sunburst_from_holdings(
                hdf,
                title=f"{picked} — sector and stock breakdown",
                root_label=short_fund_name(picked, 18),
            ),
            use_container_width=True,
        )
        st.caption(
            "Slices too small to label are still available on hover, and clicking "
            "a sector zooms into it."
        )

        st.subheader("Largest look-through holdings")
        if analysis.top_holdings:
            top_df = pd.DataFrame(analysis.top_holdings).rename(
                columns={"security": "Security", "weight_pct": "Portfolio weight %"}
            )
            st.dataframe(
                top_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Portfolio weight %": st.column_config.ProgressColumn(
                        "Portfolio weight %",
                        min_value=0,
                        max_value=float(max(top_df["Portfolio weight %"].max(), 1.0)),
                        format="%.2f%%",
                    )
                },
            )
        else:
            # Fast mode skips the stock-level fetch, so this table was silently
            # blank for any portfolio big enough to trigger it.
            empty_state(
                "Look-through holdings need a deep analysis",
                "Fast mode skips the stock-level fetch for large portfolios. "
                "Turn on Deep analysis above to aggregate stock weights across "
                "every fund.",
                icon="🔍",
            )

with tab3:
    if analysis.correlation:
        st.plotly_chart(
            correlation_heatmap(pd.DataFrame(analysis.correlation)),
            use_container_width=True,
        )
    # Risk-return of sleeves
    rows = []
    for h in init_portfolio_holdings():
        a = svc.compute_fund_analytics(str(h["amfi_code"]))
        m = a["metrics"]
        rows.append(
            {
                "name": (h.get("scheme_name") or "")[:40],
                "volatility": m.get("volatility") or 0,
                "cagr": m.get("cagr") or 0,
            }
        )
    if rows:
        st.plotly_chart(risk_return_scatter(pd.DataFrame(rows)), use_container_width=True)

with tab4:
    series = {}
    for h in init_portfolio_holdings():
        name = (h.get("scheme_name") or h["amfi_code"])[:30]
        nav = svc.get_nav_history(str(h["amfi_code"]), name)
        series[name] = nav.pct_change()
    rets = pd.DataFrame(series).dropna(how="all").fillna(0)
    res = PortfolioOptimizer().max_sharpe(rets)
    st.plotly_chart(efficient_frontier(res.efficient_frontier), use_container_width=True)
    from frontend.components.ui_blocks import weights_bar

    st.plotly_chart(weights_bar(res.weights, "Max-Sharpe weights"), use_container_width=True)
