"""Module 11 — Mutual Fund X-Ray (visual-first)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.xray import FundXRay
from frontend.components.charts import gauge_score, sunburst_from_holdings
from frontend.components.ui_blocks import (
    allocation_donut,
    horizontal_bar,
    insight_cards,
    score_pill,
    tip_list,
    top_holdings_bar,
)
from frontend.components.provenance import provenance_for_codes, render_provenance
from frontend.state import get_fund_service
from frontend.components.page import page_header
from frontend.theme import apply_theme

apply_theme()

page_header(
    "Mutual Fund X-Ray",
    "Hidden risks, style, concentration, costs — plain language with charts.",
    "🔬",
)

svc = get_fund_service()
q = st.text_input("Search fund", "mid cap")
df = svc.search_funds(q, limit=20)
if df.empty:
    st.warning("No funds.")
    st.stop()

name = st.selectbox("Fund", df["scheme_name"].tolist())
code = str(df.loc[df["scheme_name"] == name, "amfi_code"].iloc[0])

with st.spinner("Running X-Ray…"):
    a = svc.compute_fund_analytics(code)
    report = FundXRay().analyze(
        scheme_name=name,
        nav=a["nav"],
        holdings=a["holdings"],
        expense_ratio=a.get("expense_ratio"),
        manager_tenure=a.get("manager_tenure"),
        aum_cr=a.get("aum_cr"),
        category=a["meta"].get("category"),
        riskometer=a["meta"].get("riskometer"),
    )

render_provenance(
    provenance_for_codes(svc, entries=[(name, code)]), what="This X-Ray"
)

h = report.overall_health
score_pill(h.overall, report.scheme_name[:50])
st.write(report.summary)

c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(gauge_score(h.overall, "Overall Health"), use_container_width=True)
    st.subheader("Hidden risks")
    tip_list(report.hidden_risks, title="")
with c2:
    if report.sector_bias:
        st.plotly_chart(
            allocation_donut(report.sector_bias, "Sector bias"),
            use_container_width=True,
        )
    if report.market_cap_bias:
        st.plotly_chart(
            allocation_donut(report.market_cap_bias, "Market cap bias"),
            use_container_width=True,
        )

st.subheader("Holdings map")
hdf = a.get("holdings")
if hdf is not None and not getattr(hdf, "empty", True):
    try:
        fig_sb = sunburst_from_holdings(hdf, "Holdings map (sector → stock)")
        st.plotly_chart(fig_sb, use_container_width=True)
        st.caption(
            "Inner ring = sector, outer = stocks. Negative / zero weights are excluded. "
            "Hover a slice for weight %."
        )
    except Exception as exc:
        st.warning(f"Sunburst chart unavailable: {exc}")
        # Minimal fallback bar of top weights
        try:
            tmp = hdf.copy()
            wcol = "weight_pct" if "weight_pct" in tmp.columns else None
            ncol = "security_name" if "security_name" in tmp.columns else None
            if wcol and ncol:
                tmp[wcol] = pd.to_numeric(tmp[wcol], errors="coerce")
                top = tmp[tmp[wcol] > 0].nlargest(15, wcol)
                st.bar_chart(top.set_index(ncol)[wcol])
        except Exception:
            st.caption("Holdings table is still available below under Top concentration.")
else:
    st.info("No holdings available for this fund yet.")

st.subheader("Diagnostics at a glance")
diag = [
    {"Area": "Style", "Finding": report.style_drift or "—"},
    {"Area": "Manager", "Finding": report.manager_dependency or "—"},
    {"Area": "Expense", "Finding": report.expense_analysis or "—"},
    {"Area": "Stability", "Finding": report.historical_stability or "—"},
    {"Area": "Benchmark", "Finding": report.benchmark_comparison or "—"},
]
st.dataframe(pd.DataFrame(diag), use_container_width=True, hide_index=True)

st.subheader("Top concentration")
if report.hidden_concentration:
    st.plotly_chart(
        top_holdings_bar(
            report.hidden_concentration,
            "Largest positions",
            name_key="security",
            weight_key="weight_pct",
        ),
        use_container_width=True,
    )
    st.dataframe(
        pd.DataFrame(report.hidden_concentration).rename(
            columns={"security": "Security", "weight_pct": "Weight %"}
        ),
        use_container_width=True,
        hide_index=True,
    )

st.subheader("Suggested alternatives")
tip_list(report.suggested_alternatives, title="")
