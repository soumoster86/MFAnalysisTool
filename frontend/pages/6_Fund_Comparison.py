"""Module 6 — Mutual Fund Comparison (up to 5)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.components.charts import line_nav, risk_return_scatter
from frontend.components.ui_blocks import risk_return_ranking_table
from frontend.components.provenance import provenance_for_codes, render_provenance
from frontend.state import get_fund_service
from frontend.theme import apply_theme
from services.ai.assistant import FinancialAssistant
from utils.helpers import pct

apply_theme()

st.title("Mutual Fund Comparison")
st.caption("Compare up to 5 funds · risk metrics · capture ratios · AI summary")

svc = get_fund_service()
q = st.text_input("Search to add funds", "direct growth")
pool = svc.search_funds(q, limit=40)
if pool.empty:
    st.warning("No schemes available.")
    st.stop()

selected = st.multiselect(
    "Select up to 5 funds",
    options=pool["scheme_name"].tolist(),
    max_selections=5,
    default=pool["scheme_name"].tolist()[:2],
)

if len(selected) < 2:
    st.info("Select at least 2 funds.")
    st.stop()

rows = []
navs = {}
for name in selected:
    code = str(pool.loc[pool["scheme_name"] == name, "amfi_code"].iloc[0])
    with st.spinner(f"Analyzing {name[:40]}…"):
        a = svc.compute_fund_analytics(code)
    m = a["metrics"]
    rows.append(
        {
            "name": name[:50],
            "amfi_code": code,
            "health": a["health"]["overall"],
            "cagr": m.get("cagr"),
            "volatility": m.get("volatility"),
            "sharpe": m.get("sharpe"),
            "sortino": m.get("sortino"),
            "alpha": m.get("alpha"),
            "beta": m.get("beta"),
            "max_drawdown": m.get("max_drawdown"),
            "expense_ratio": a.get("expense_ratio"),
            "upside_capture": m.get("upside_capture"),
            "downside_capture": m.get("downside_capture"),
            "capture_ratio": m.get("capture_ratio"),
        }
    )
    navs[name[:40]] = a["nav"]

render_provenance(
    provenance_for_codes(svc, entries=[(r["name"], r["amfi_code"]) for r in rows]),
    what="This comparison",
)

cmp_df = pd.DataFrame(rows)
st.dataframe(
    cmp_df.style.format(
        {
            "cagr": lambda x: pct(x) if pd.notna(x) else "—",
            "volatility": lambda x: pct(x) if pd.notna(x) else "—",
            "max_drawdown": lambda x: pct(x) if pd.notna(x) else "—",
            "alpha": lambda x: pct(x) if pd.notna(x) else "—",
            "sharpe": "{:.2f}",
            "sortino": "{:.2f}",
            "beta": "{:.2f}",
            "health": "{:.0f}",
        },
        na_rep="—",
    ),
    use_container_width=True,
    hide_index=True,
)

# Normalized NAV comparison chart
from frontend.components.charts import multi_nav_normalized

st.subheader("NAV path comparison")
st.caption(
    "Each fund is rebased to **100** at the start of its series so growth is comparable. "
    "Hover for date and index level."
)
st.plotly_chart(multi_nav_normalized(navs), use_container_width=True)

scatter_df = cmp_df.dropna(subset=["volatility", "cagr"])
if not scatter_df.empty:
    st.subheader("Risk vs return")
    st.caption(
        "How to read this chart: **right = more ups-and-downs (risk)**, **up = higher historical return**. "
        "The **green zone (top-left)** is generally preferable. **Larger bubbles** mean a better Sharpe ratio "
        "(more return per unit of risk). Hover a bubble for full details."
    )
    st.plotly_chart(
        risk_return_scatter(
            scatter_df,
            x="volatility",
            y="cagr",
            size="sharpe",
            hover="name",
            label_col="name",
            title="Risk vs Return",
            show_quadrants=True,
            show_labels=True,
        ),
        use_container_width=True,
    )

    rank = risk_return_ranking_table(scatter_df)
    if not rank.empty:
        st.markdown("**Quick ranking (easier than reading dots alone)**")
        st.dataframe(
            rank,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Return (CAGR)": st.column_config.NumberColumn("Return (CAGR %)", format="%.1f%%"),
                "Risk (Vol %)": st.column_config.NumberColumn("Risk (Vol %)", format="%.1f%%"),
                "Sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
                "Return / Risk": st.column_config.NumberColumn("Return / Risk", format="%.2f"),
            },
        )
        # One-line takeaway
        top = rank.iloc[0]
        st.success(
            f"**Best risk-adjusted on this set:** {top['Fund']} "
            f"(Sharpe {top['Sharpe'] if pd.notna(top['Sharpe']) else 'n/a'} · "
            f"return {top['Return (CAGR)']}% · risk {top['Risk (Vol %)']}%). "
            f"Reading: {top['Reading']}."
        )

if st.button("Generate AI comparison summary"):
    assistant = FinancialAssistant()
    ctx = assistant.build_context(comparison={"funds": rows})
    out = assistant.chat(
        "Compare these mutual funds for a long-term SIP investor. Be concise and cite the metrics.",
        context=ctx,
    )
    st.markdown(out["reply"])
    st.caption(f"Source: {out['source']}")
