"""Module 13 — Alerts."""

from __future__ import annotations

import streamlit as st

from frontend.state import init_portfolio_holdings
from frontend.theme import apply_theme
from services.alerts.alert_service import AlertService
from workers.tasks import evaluate_alerts, refresh_amfi

apply_theme()

st.title("Alerts")
st.caption("Manager · expense · NAV · drawdown · overlap · Celery-ready hooks")

svc = AlertService()
svc.seed_demo_alerts()

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Seed demo alerts"):
        n = svc.seed_demo_alerts()
        st.success(f"Seeded {n} (0 if already present)")
with c2:
    if st.button("Evaluate portfolio NAV alerts"):
        codes = [str(h["amfi_code"]) for h in init_portfolio_holdings()]
        with st.spinner("Evaluating…"):
            out = evaluate_alerts(codes)
        st.json(out)
with c3:
    if st.button("Queue AMFI refresh task"):
        out = refresh_amfi.delay(True) if hasattr(refresh_amfi, "delay") else refresh_amfi(True)
        st.write(out)

unread_only = st.checkbox("Unread only", False)
alerts = svc.list_alerts(unread_only=unread_only)

if not alerts:
    st.info("No alerts.")
else:
    for a in alerts:
        color = {"critical": "🔴", "warning": "🟠", "info": "🔵"}.get(a["severity"], "⚪")
        with st.container():
            st.markdown(f"{color} **{a['title']}** · `{a['alert_type']}` · {a['created_at']}")
            st.write(a["message"])
            if not a["is_read"] and st.button("Mark read", key=f"read_{a['id']}"):
                svc.mark_read(a["id"])
                st.rerun()
            st.markdown("---")
