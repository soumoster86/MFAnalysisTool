"""Module 15 — Reports (PDF / Excel / PPTX)."""

from __future__ import annotations

import streamlit as st

from frontend.components.provenance import render_provenance
from frontend.state import get_portfolio_analyzer, init_portfolio_holdings
from services.data.provenance import Provenance
from frontend.theme import apply_theme
from services.ai.assistant import FinancialAssistant
from services.reports.report_service import ReportService
from utils.helpers import format_inr, pct

apply_theme()

st.title("Reports")
st.caption("PDF · Excel · PowerPoint · optional AI summary")

analysis = get_portfolio_analyzer().analyze(init_portfolio_holdings())
report_svc = ReportService()

render_provenance(analysis.data_sources, what="This report's figures")

summary_lines = [
    f"Portfolio value: {format_inr(analysis.total_current)}",
    f"Invested: {format_inr(analysis.total_invested)}",
    f"P&L: {format_inr(analysis.overall_gain)} ({pct(analysis.overall_gain_pct)})",
    f"Health score: {analysis.health_score}/100",
    f"CAGR: {pct(analysis.portfolio_cagr) if analysis.portfolio_cagr is not None else 'N/A'}",
    f"Volatility: {pct(analysis.volatility) if analysis.volatility is not None else 'N/A'}",
    f"Sharpe: {analysis.sharpe:.2f}" if analysis.sharpe is not None else "Sharpe: N/A",
]

# A generated file outguns any on-screen banner — it gets read detached from
# this page, so the disclosure has to travel inside it.
_prov = Provenance.from_dict(analysis.data_sources)
if _prov.has_fabricated:
    summary_lines.append(
        f"DATA WARNING: {len(_prov.fabricated_nav)} fund(s) used synthetic NAV and "
        f"{len(_prov.fabricated_holdings)} used sample holdings. Figures above are "
        "illustrative and do not match published returns."
    )

for line in summary_lines:
    st.write(f"- {line}")

ai_summary = ""
if st.checkbox("Include AI summary", value=False):
    assistant = FinancialAssistant()
    ctx = assistant.build_context(
        portfolio_summary={
            "value": analysis.total_current,
            "health": analysis.health_score,
            "cagr": analysis.portfolio_cagr,
            "vol": analysis.volatility,
            "allocation": analysis.asset_allocation,
        }
    )
    out = assistant.chat(
        "Write a 5-bullet portfolio review for a long-term investor. Cite the provided metrics.",
        context=ctx,
    )
    ai_summary = out["reply"]
    st.markdown(ai_summary)

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Generate Excel", use_container_width=True):
        path = report_svc.generate_excel(
            portfolio_rows=analysis.holdings_detail,
            metrics={
                "cagr": analysis.portfolio_cagr,
                "vol": analysis.volatility,
                "sharpe": analysis.sharpe,
            },
            health={"overall": analysis.health_score},
        )
        st.success(f"Saved: {path}")
        with open(path, "rb") as f:
            st.download_button("Download Excel", f, file_name=path.name)

with c2:
    if st.button("Generate PDF", use_container_width=True):
        path = report_svc.generate_pdf(
            title="MF Analysis Portfolio Report",
            summary_lines=summary_lines,
            table_rows=analysis.holdings_detail,
            ai_summary=ai_summary,
        )
        st.success(f"Saved: {path}")
        with open(path, "rb") as f:
            st.download_button("Download PDF", f, file_name=path.name)

with c3:
    if st.button("Generate PowerPoint", use_container_width=True):
        path = report_svc.generate_pptx(
            title="MF Portfolio Review",
            bullets=summary_lines,
            metrics={
                "Health": analysis.health_score,
                "Value": analysis.total_current,
                "CAGR": analysis.portfolio_cagr,
            },
        )
        st.success(f"Saved: {path}")
        with open(path, "rb") as f:
            st.download_button("Download PPTX", f, file_name=path.name)
