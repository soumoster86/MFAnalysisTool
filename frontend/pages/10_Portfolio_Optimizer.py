"""Module 10 — Portfolio Optimizer."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.optimizer import PortfolioOptimizer
from frontend.components.charts import efficient_frontier
from frontend.state import get_fund_service, init_portfolio_holdings
from frontend.theme import apply_theme
from utils.helpers import pct

apply_theme()

st.title("Portfolio Optimizer")
st.caption("Mean-variance · Max Sharpe · Min Variance · Risk Parity · Black-Litterman (simple)")

svc = get_fund_service()
holdings = init_portfolio_holdings()
codes = [str(h["amfi_code"]) for h in holdings]

method = st.selectbox(
    "Method",
    ["max_sharpe", "min_variance", "risk_parity", "black_litterman", "equal_weight"],
)

if st.button("Optimize", type="primary"):
    with st.spinner("Building return matrix…"):
        series = {}
        for h in holdings:
            code = str(h["amfi_code"])
            name = h.get("scheme_name") or code
            nav = svc.get_nav_history(code, name)
            series[name[:40]] = nav.pct_change()
        rets = pd.DataFrame(series).dropna(how="all").fillna(0)
        opt = PortfolioOptimizer()
        if method == "min_variance":
            res = opt.min_variance(rets)
        elif method == "risk_parity":
            res = opt.risk_parity(rets)
        elif method == "black_litterman":
            res = opt.black_litterman_simple(rets)
        elif method == "equal_weight":
            res = opt.equal_weight(rets)
        else:
            res = opt.max_sharpe(rets)
        # Always attach frontier from max_sharpe helper
        if not res.efficient_frontier:
            res.efficient_frontier = opt.max_sharpe(rets).efficient_frontier
        st.session_state["opt_result"] = res

res = st.session_state.get("opt_result")
if not res:
    st.info("Run optimizer on current portfolio funds.")
    st.stop()

from frontend.components.ui_blocks import insight_cards, weights_bar, short_fund_name
import pandas as pd

insight_cards(
    [
        {
            "label": "Expected return",
            "value": pct(res.expected_return),
            "help": f"Method: {res.method.replace('_', ' ')}",
            "tone": "good",
        },
        {
            "label": "Expected risk",
            "value": pct(res.expected_risk),
            "help": "Annualized volatility of suggested mix",
            "tone": "warn" if res.expected_risk > 0.18 else "neutral",
        },
        {
            "label": "Sharpe ratio",
            "value": f"{res.sharpe:.2f}",
            "help": "Higher = better risk-adjusted return",
            "tone": "good" if res.sharpe > 0.8 else "neutral",
        },
    ],
    cols=3,
)

st.subheader(f"Suggested weights ({res.method.replace('_', ' ')})")
st.caption("How much of the portfolio to put in each fund under this optimization.")
st.plotly_chart(weights_bar(res.weights, "Optimized allocation"), use_container_width=True)

wdf = pd.DataFrame(
    [
        {
            "Fund": short_fund_name(k, 40),
            "Weight %": round((v * 100 if v <= 1 else v), 1),
        }
        for k, v in sorted(res.weights.items(), key=lambda x: -x[1])
    ]
)
st.dataframe(
    wdf,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Weight %": st.column_config.ProgressColumn(
            "Weight %", min_value=0, max_value=100, format="%.1f%%"
        )
    },
)

if res.efficient_frontier:
    st.subheader("Efficient frontier")
    st.caption("Each point is a diversified mix — left is lower risk, up is higher expected return.")
    st.plotly_chart(efficient_frontier(res.efficient_frontier), use_container_width=True)

if res.notes:
    st.caption(res.notes)
