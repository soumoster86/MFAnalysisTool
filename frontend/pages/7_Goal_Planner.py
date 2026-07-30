"""Module 7 — Goal Planner with Monte Carlo."""

from __future__ import annotations

import streamlit as st

import plotly.graph_objects as go

from analytics.goal_planner import GoalPlanner
from frontend.components.charts import monte_carlo_hist
from frontend.components.page import page_header
from frontend.theme import INFO, apply_theme, style_fig
from utils.helpers import format_inr, pct

apply_theme()

page_header(
    "Goal Planner",
    "Retirement / goal corpus · Monte Carlo · required SIP & return",
    "🎯",
)

c1, c2, c3 = st.columns(3)
with c1:
    age = st.number_input("Current age", 18, 70, 30)
    retirement_age = st.number_input("Target age", 30, 80, 60)
    current = st.number_input("Current investment ₹", 0, 100_000_000, 500_000, step=50_000)
with c2:
    sip = st.number_input("Monthly SIP ₹", 0, 5_000_000, 20_000, step=1000)
    exp_ret = st.slider("Expected annual return", 0.04, 0.20, 0.12, 0.005)
    inflation = st.slider("Expected inflation", 0.02, 0.10, 0.06, 0.005)
with c3:
    goal = st.number_input("Goal amount ₹ (0 = auto)", 0, 500_000_000, 0, step=100_000)
    vol = st.slider("Return volatility", 0.02, 0.30, 0.15, 0.01)
    n_sim = st.slider("Simulations", 500, 5000, 2000, 500)

if st.button("Run plan", type="primary"):
    with st.spinner("Running Monte Carlo…"):
        res = GoalPlanner().plan(
            age=int(age),
            retirement_age=int(retirement_age),
            current_investment=float(current),
            monthly_sip=float(sip),
            expected_return=float(exp_ret),
            expected_inflation=float(inflation),
            goal_amount=float(goal) if goal > 0 else None,
            return_volatility=float(vol),
            n_simulations=int(n_sim),
        )
    st.session_state["goal_result"] = res

res = st.session_state.get("goal_result")
if not res:
    st.info("Configure inputs and click **Run plan**.")
    st.stop()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Expected corpus", format_inr(res.expected_corpus))
k2.metric("P(success)", f"{res.probability_of_success:.1%}")
k3.metric("Required SIP", format_inr(res.required_sip))
k4.metric(
    "Required return",
    pct(res.required_return) if res.required_return is not None else "—",
)

c1, c2, c3 = st.columns(3)
c1.metric("Worst (p5)", format_inr(res.worst_case))
c2.metric("Average", format_inr(res.average_case))
c3.metric("Best (p95)", format_inr(res.best_case))

# Median path
fig = go.Figure()
fig.add_trace(go.Scatter(y=res.monthly_path_median, mode="lines", name="Median path"))
for i, path in enumerate(res.simulation_paths_sample[:8]):
    fig.add_trace(
        go.Scatter(y=path, mode="lines", name=f"sim{i}", opacity=0.35, showlegend=False)
    )
fig.update_layout(title="Corpus path (downsampled)", yaxis_title="₹")
st.plotly_chart(style_fig(fig), use_container_width=True)

st.write(res.notes)

st.subheader("Outcome range (Monte Carlo)")
st.caption("Percentiles of simulated terminal corpus — p5 is a bad market path, p95 is a strong one.")
if res.percentiles:
    from frontend.components.ui_blocks import horizontal_bar, insight_cards
    import pandas as pd

    insight_cards(
        [
            {"label": "Pessimistic (p5)", "value": format_inr(res.percentiles.get("p5", res.worst_case)), "tone": "bad"},
            {"label": "Median (p50)", "value": format_inr(res.percentiles.get("p50", res.average_case)), "tone": "neutral"},
            {"label": "Optimistic (p95)", "value": format_inr(res.percentiles.get("p95", res.best_case)), "tone": "good"},
        ],
        cols=3,
    )
    labels = {
        "p5": "Worst 5%",
        "p25": "Lower 25%",
        "p50": "Median",
        "p75": "Upper 75%",
        "p95": "Best 5%",
    }
    chart = {labels.get(k, k): float(v) for k, v in res.percentiles.items()}
    st.plotly_chart(
        horizontal_bar(chart, "Terminal corpus by percentile (₹)", x_title="₹", color=INFO),
        use_container_width=True,
    )
    st.dataframe(
        pd.DataFrame(
            [{"Outcome": labels.get(k, k), "Corpus ₹": round(float(v), 0)} for k, v in res.percentiles.items()]
        ),
        use_container_width=True,
        hide_index=True,
    )
