"""Module 9 — Recommendation Engine."""

from __future__ import annotations

import streamlit as st

from frontend.components.page import page_header
from frontend.theme import apply_theme
from ml.recommender import RecommendationEngine
from utils.helpers import format_inr, pct

apply_theme()

page_header(
    "Recommendation Engine",
    "Risk appetite · horizon · SIP · age → ranked funds & allocation",
    "✨",
)

c1, c2 = st.columns(2)
with c1:
    risk = st.selectbox("Risk appetite", ["Conservative", "Moderate", "Aggressive", "Very Aggressive"], index=1)
    horizon = st.slider("Investment horizon (years)", 1, 30, 7)
    age = st.number_input("Age", 18, 80, 32)
with c2:
    sip = st.number_input("Monthly SIP ₹", 500, 1_000_000, 15_000, step=500)
    goals = st.text_input("Goals (optional)", "Retirement corpus + child education")
    max_funds = st.slider("Max funds", 3, 8, 5)

if st.button("Generate recommendations", type="primary"):
    with st.spinner("Scoring universe…"):
        res = RecommendationEngine().recommend(
            risk_appetite=risk,
            investment_horizon=int(horizon),
            monthly_sip=float(sip),
            age=int(age),
            goals=goals,
            max_funds=int(max_funds),
        )
        st.session_state["reco"] = res

res = st.session_state.get("reco")
if not res:
    st.info("Configure profile and generate.")
    st.stop()

st.write(res.risk_analysis)
k1, k2 = st.columns(2)
k1.metric("Expected return (blend)", pct(res.expected_return or 0) if res.expected_return else "—")
k2.metric("Expected risk (blend)", pct(res.expected_risk or 0) if res.expected_risk else "—")

st.subheader("Recommended funds")
st.dataframe(res.recommended_funds, use_container_width=True, hide_index=True)

st.subheader("Suggested allocation")
from frontend.components.ui_blocks import weights_bar, short_fund_name
import pandas as pd

if res.allocation:
    st.plotly_chart(
        weights_bar(res.allocation, "Target mix"),
        use_container_width=True,
    )
    st.subheader(f"Monthly SIP split ({format_inr(sip)}/mo)")
    split_rows = [
        {
            "Fund": short_fund_name(k, 42),
            "Weight %": round(v * 100, 1),
            "SIP ₹ / month": round(v * sip, 0),
        }
        for k, v in sorted(res.allocation.items(), key=lambda x: -x[1])
    ]
    st.dataframe(
        pd.DataFrame(split_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Weight %": st.column_config.ProgressColumn(
                "Weight %", min_value=0, max_value=100, format="%.1f%%"
            ),
            "SIP ₹ / month": st.column_config.NumberColumn("SIP ₹ / month", format="₹%.0f"),
        },
    )

for n in res.notes:
    st.caption(n)
