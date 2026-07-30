"""Module 3 — Fund Health Score (visual-first)."""

from __future__ import annotations

import streamlit as st

from frontend.components.charts import bar_scores, gauge_score
from frontend.components.ui_blocks import horizontal_bar, insight_cards, score_pill, tip_list
from frontend.components.provenance import provenance_for_codes, render_provenance
from frontend.state import get_fund_service
from frontend.components.page import page_header
from frontend.theme import POSITIVE, apply_theme
from utils.helpers import pct

apply_theme()

page_header(
    "Fund Health Score",
    "0–100 multi-factor model — growth, risk, quality, cost, consistency, diversification.",
    "💚",
)

svc = get_fund_service()
q = st.text_input("Search fund", "flexi cap")
df = svc.search_funds(q, limit=20)
if df.empty:
    st.warning("No funds found.")
    st.stop()

name = st.selectbox("Fund", df["scheme_name"].tolist())
code = str(df.loc[df["scheme_name"] == name, "amfi_code"].iloc[0])

with st.spinner("Scoring…"):
    data = svc.compute_fund_analytics(code)

health = data["health"]
metrics = data["metrics"]

score_pill(health["overall"], name[:48])
st.write(health.get("narrative", ""))

c1, c2 = st.columns([1, 1.4])
with c1:
    st.plotly_chart(gauge_score(health["overall"]), use_container_width=True)
with c2:
    pillars = {
        "Growth": health["growth"],
        "Risk": health["risk"],
        "Quality": health["quality"],
        "Cost": health["cost_efficiency"],
        "Consistency": health["consistency"],
        "Diversification": health["diversification"],
    }
    st.plotly_chart(bar_scores(pillars, "Score pillars"), use_container_width=True)

insight_cards(
    [
        {
            "label": "CAGR",
            "value": pct(metrics["cagr"]) if metrics.get("cagr") is not None else "—",
            "help": "Annualized return",
            "tone": "good" if (metrics.get("cagr") or 0) > 0.1 else "neutral",
        },
        {
            "label": "Sharpe",
            "value": f"{metrics['sharpe']:.2f}" if metrics.get("sharpe") is not None else "—",
            "help": "Return per unit risk",
            "tone": "good" if (metrics.get("sharpe") or 0) > 0.8 else "neutral",
        },
        {
            "label": "Max drawdown",
            "value": pct(metrics["max_drawdown"]) if metrics.get("max_drawdown") is not None else "—",
            "help": "Worst peak-to-trough fall",
            "tone": "bad" if (metrics.get("max_drawdown") or 0) < -0.3 else "warn",
        },
        {
            "label": "Expense ratio",
            "value": f"{data.get('expense_ratio')}%",
            "help": "Annual fund cost",
            "tone": "good" if (data.get("expense_ratio") or 99) < 1 else "warn",
        },
    ],
    cols=4,
)

m2 = st.columns(4)
pairs = [
    ("Sortino", f"{metrics['sortino']:.2f}" if metrics.get("sortino") is not None else "—"),
    ("Alpha", pct(metrics["alpha"]) if metrics.get("alpha") is not None else "—"),
    ("Beta", f"{metrics['beta']:.2f}" if metrics.get("beta") is not None else "—"),
    ("Volatility", pct(metrics["volatility"]) if metrics.get("volatility") is not None else "—"),
]
for i, (lab, val) in enumerate(pairs):
    m2[i].metric(lab, val)

factors = health.get("factors") or {}
if factors:
    st.subheader("What drives the score")
    st.caption("Each bar is a contributing factor (0–100). Higher is better for that factor.")
    st.plotly_chart(
        horizontal_bar({str(k).replace("_", " ").title(): float(v) for k, v in factors.items()},
                       "Factor contributions", color=POSITIVE),
        use_container_width=True,
    )

render_provenance(
    provenance_for_codes(svc, entries=[(name, code)]), what="These fund metrics"
)
