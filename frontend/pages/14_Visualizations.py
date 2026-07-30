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
from frontend.components.provenance import render_provenance
from frontend.state import get_fund_service, get_portfolio_analyzer, init_portfolio_holdings
from frontend.components.page import page_header
from frontend.theme import apply_theme
from analytics.optimizer import PortfolioOptimizer

apply_theme()

page_header(
    "Visualization Lab",
    "Plotly · treemap · heatmap · sunburst · frontier · drawdown · risk-return",
    "📉",
)

analysis = get_portfolio_analyzer().analyze(init_portfolio_holdings())
svc = get_fund_service()

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
    if analysis.holdings_detail:
        code = analysis.holdings_detail[0]["amfi_code"]
        hdf = svc.get_holdings(code)
        st.plotly_chart(sunburst_from_holdings(hdf), use_container_width=True)
        st.dataframe(analysis.top_holdings, use_container_width=True, hide_index=True)

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
