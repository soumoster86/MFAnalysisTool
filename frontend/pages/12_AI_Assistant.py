"""Module 12 — AI Financial Assistant."""

from __future__ import annotations

import streamlit as st

from frontend.components.provenance import render_provenance
from frontend.state import get_portfolio_analyzer, init_portfolio_holdings
from frontend.components.page import page_header
from frontend.theme import apply_theme
from services.ai.assistant import FinancialAssistant
from services.data.provenance import Provenance

apply_theme()

page_header(
    "AI Financial Assistant",
    "Retrieval-grounded answers with citations · portfolio context · "
    "works without an API key",
    "💬",
)

assistant = FinancialAssistant()
if assistant.is_configured:
    st.success(f"Connected · model `{assistant.model}`")
else:
    st.info(
        "No OPENAI_API_KEY — answers come straight from the knowledge base with "
        "citations, without a model to summarise them."
    )

try:
    from services.ai.retriever import get_retriever

    _r = get_retriever()
    st.caption(f"Knowledge base: **{_r.size}** passages · retrieval `{_r.backend}`")
except Exception as _exc:
    st.caption(f"Knowledge base unavailable: {_exc}")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

render_provenance(
    st.session_state.get("chat_provenance"), what="The portfolio figures given to the assistant"
)

inject = st.checkbox("Inject current portfolio context", value=True)
style = st.selectbox(
    "Answer style hint",
    ["Default", "Explain like a beginner", "Explain like Warren Buffett", "Use examples"],
)

# Display history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Ask about SIPs, alpha, compare funds, portfolio health…")
if prompt:
    user_text = prompt
    if style != "Default":
        user_text = f"{prompt}\n\n(Style: {style})"

    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    ctx = ""
    if inject:
        try:
            analysis = get_portfolio_analyzer().analyze(init_portfolio_holdings())
            summary = {
                "value": analysis.total_current,
                "invested": analysis.total_invested,
                "health_score": analysis.health_score,
                "cagr": analysis.portfolio_cagr,
                "volatility": analysis.volatility,
                "sharpe": analysis.sharpe,
                "asset_allocation": analysis.asset_allocation,
                "top_holdings": analysis.top_holdings[:5],
            }
            # The model is told to treat CONTEXT as authoritative and cite it.
            # If any of it came from a synthetic NAV path, say so inside the
            # context itself — otherwise the assistant states fabricated
            # figures as fact, which is exactly what it must never do.
            prov = Provenance.from_dict(analysis.data_sources)
            extra = None
            if prov.has_fabricated:
                extra = (
                    "DATA CAVEAT: some figures above derive from SYNTHETIC NAV or "
                    f"SAMPLE holdings ({len(prov.fabricated_nav)} fund(s) synthetic NAV, "
                    f"{len(prov.fabricated_holdings)} sample holdings) because live "
                    "providers failed. You MUST state this caveat when citing any "
                    "affected number, and must not present it as real performance."
                )
            ctx = assistant.build_context(portfolio_summary=summary, extra=extra)
            st.session_state["chat_provenance"] = analysis.data_sources
        except Exception as exc:
            ctx = assistant.build_context(extra=f"Portfolio context error: {exc}")

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            out = assistant.chat(
                user_text,
                context=ctx,
                history=[
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.chat_history[:-1]
                ][-8:],
            )
        st.markdown(out["reply"])
        cites = out.get("citations") or []
        if cites:
            st.caption("Sources: " + " · ".join(f"`{c}`" for c in cites))
        st.caption(f"source={out['source']} model={out.get('model')}")
    st.session_state.chat_history.append({"role": "assistant", "content": out["reply"]})

if st.button("Clear chat"):
    st.session_state.chat_history = []
    st.rerun()
