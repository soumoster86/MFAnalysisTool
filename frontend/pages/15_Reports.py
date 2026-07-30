"""Module 15 — Reports (PDF / Excel / PowerPoint)."""

from __future__ import annotations

import traceback

import pandas as pd
import streamlit as st

from frontend.components.provenance import render_provenance
from frontend.state import get_cached_analysis, init_portfolio_holdings
from frontend.components.page import page_header
from frontend.theme import apply_theme
from services.ai.assistant import FinancialAssistant
from services.reports.report_service import ReportService

apply_theme()

page_header(
    "Reports",
    "Branded PDF · formatted Excel workbook · PowerPoint deck — "
    "charts, tables and data-source disclosure included",
    "📄",
)

holdings = init_portfolio_holdings()
if not holdings:
    st.info(
        "No portfolio loaded. Import a CAS, open a saved portfolio, or add "
        "holdings from the Dashboard, then come back."
    )
    st.stop()

try:
    analysis = get_cached_analysis(holdings)
except Exception as exc:
    st.error("Could not analyse the portfolio.")
    st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
    st.stop()

report_svc = ReportService()
render_provenance(analysis.data_sources, what="This report's figures")

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
with st.expander("Report options", expanded=False):
    o1, o2 = st.columns(2)
    with o1:
        title = st.text_input("Report title", "Portfolio Analysis Report")
        subtitle = st.text_input(
            "Subtitle", "", placeholder="Client name, review period, adviser…"
        )
    with o2:
        max_holdings = st.slider("Holdings to list", 10, 100, 40, step=10)
        include_ai = st.checkbox(
            "Include AI review",
            value=False,
            help="Adds a written review. Needs an OpenAI-compatible key.",
        )

ai_summary = ""
if include_ai:
    with st.spinner("Writing the review…"):
        try:
            assistant = FinancialAssistant()
            ctx = assistant.build_context(
                portfolio_summary={
                    "value": analysis.total_current,
                    "invested": analysis.total_invested,
                    "health": analysis.health_score,
                    "cagr": analysis.portfolio_cagr,
                    "volatility": analysis.volatility,
                    "sharpe": analysis.sharpe,
                    "allocation": analysis.asset_allocation,
                }
            )
            out = assistant.chat(
                "Write a concise 5-point portfolio review for a long-term investor. "
                "Cite the provided metrics. Plain sentences, no markdown headings.",
                context=ctx,
            )
            ai_summary = out.get("reply", "")
        except Exception as exc:
            st.warning(f"AI review unavailable: {type(exc).__name__}: {exc}")

try:
    data = report_svc.from_analysis(
        analysis,
        title=title,
        subtitle=subtitle,
        ai_summary=ai_summary,
        max_holdings=max_holdings,
    )
except Exception as exc:
    st.error("Could not assemble the report.")
    st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
    st.stop()

# ---------------------------------------------------------------------------
# Preview — the same content the files will carry
# ---------------------------------------------------------------------------
st.subheader("Preview")
cols = st.columns(3)
for i, kpi in enumerate(data.kpis):
    delta = kpi.caption if kpi.tone in {"good", "bad"} else None
    cols[i % 3].metric(kpi.label, kpi.value, delta=delta, help=kpi.caption)

if data.has_warning:
    st.warning(f"**Data quality notice.** {data.data_warning}")

tabs = st.tabs(["Holdings", "Allocation", "Risk", "Sources"])

with tabs[0]:
    if data.holdings_display:
        st.dataframe(
            pd.DataFrame(data.holdings_display),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            f"Listing the largest {len(data.holdings_display)} of "
            f"{len(analysis.holdings_detail or [])} schemes."
        )
    else:
        st.info("No holdings to list.")

with tabs[1]:
    if data.allocations:
        for name, mapping in data.allocations.items():
            st.markdown(f"**{name}**")
            frame = pd.DataFrame(
                {"Bucket": list(mapping), "Weight %": list(mapping.values())}
            )
            st.bar_chart(frame.set_index("Bucket"), height=220)
        if data.top_holdings:
            st.markdown("**Largest look-through holdings**")
            st.bar_chart(
                pd.DataFrame(data.top_holdings, columns=["Security", "Weight %"]).set_index(
                    "Security"
                ),
                height=260,
            )
    else:
        st.info("Allocation needs stock-level holdings — run a deep analysis.")

with tabs[2]:
    st.table(pd.DataFrame(data.risk.rows, columns=["Metric", "Value"]))
    st.caption(data.risk.note)
    if data.overlap_rows:
        st.markdown("**Fund overlap**")
        st.table(pd.DataFrame(data.overlap_rows, columns=["Measure", "Value"]))

with tabs[3]:
    if data.source_rows:
        st.dataframe(
            pd.DataFrame(data.source_rows, columns=["Fund", "Source"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No per-fund source detail recorded for this analysis.")
    if data.notes:
        st.markdown("**Analysis notes**")
        for note in data.notes:
            st.caption(f"• {note}")

if ai_summary:
    st.subheader("AI review")
    st.write(ai_summary)

# ---------------------------------------------------------------------------
# Downloads — rendered on demand, one click each
# ---------------------------------------------------------------------------
st.subheader("Download")
st.caption(
    "Each file carries the figures above, its own charts, and the data-source "
    "disclosure — a report is read away from this page."
)

FORMATS = [
    ("pdf", "PDF report", "Branded, paginated, chart-led — for sharing or print."),
    ("excel", "Excel workbook", "Summary, Holdings, Allocation and Sources sheets with live charts."),
    ("pptx", "PowerPoint deck", "Title, KPI, allocation and holdings slides."),
]

dcols = st.columns(3)
for (fmt, label, blurb), col in zip(FORMATS, dcols):
    with col:
        st.markdown(f"**{label}**")
        st.caption(blurb)
        try:
            payload, filename, mime = report_svc.render(data, fmt)
            st.download_button(
                f"Download {fmt.upper()}",
                payload,
                file_name=filename,
                mime=mime,
                use_container_width=True,
                key=f"dl_{fmt}",
            )
            st.caption(f"{len(payload) / 1024:,.0f} KB")
        except Exception as exc:
            st.error(f"{label} failed")
            st.code(f"{type(exc).__name__}: {exc}")

csv = report_svc.holdings_csv(data)
if csv:
    st.download_button(
        "Download holdings as CSV",
        csv,
        file_name="holdings.csv",
        mime="text/csv",
    )
